"""The editor's draft model: fetch, edit locally, publish, discard."""

from __future__ import annotations

import pytest
from app.core.exceptions import (
    CampaignNotTrackedError,
    NothingToPublishError,
    OfferAlreadyAttachedError,
    OfferNotAttachedError,
    PinnedSharesExceededError,
)
from app.keitaro import builders
from app.services.draft import CampaignDraftService
from app.services.stats import DateRange

from tests.fakes import FakeKeitaro

PERIOD = DateRange.last_days(7)
GEO_OFFER = 4100
EXTRA_OFFER = 3749
THIRD_OFFER = 3717


@pytest.fixture
async def campaign_id(keitaro: FakeKeitaro) -> int:
    """A campaign with a geo redirect stream and an offer stream."""
    campaign = await keitaro.create_campaign({"name": "test_ivanov_c1"})
    await keitaro.create_stream(
        builders.build_geo_redirect_stream_payload(
            campaign_id=campaign.id, country_code="AU", redirect_url="https://google.com"
        )
    )
    await keitaro.create_stream(
        builders.build_offer_stream_payload(campaign_id=campaign.id, offer_ids=[GEO_OFFER])
    )
    return campaign.id


def offers_of(draft) -> list[tuple[int, int, str]]:  # type: ignore[no-untyped-def]
    stream = next(s for s in draft.streams if s.holds_offers)
    return [(o.offer_id, o.share, o.state.value) for o in stream.offers]


def keitaro_offers(keitaro: FakeKeitaro, campaign_id: int) -> list[tuple[int, int]]:
    stream = keitaro.offer_stream_of(campaign_id)
    assert stream is not None
    return [(o["offer_id"], o["share"]) for o in stream["offers"]]


class TestFetch:
    async def test_requires_a_fetch_before_anything_else(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        with pytest.raises(CampaignNotTrackedError):
            await draft_service.load(campaign_id, PERIOD)

    async def test_pulls_streams_and_offers(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        draft = await draft_service.load(campaign_id, PERIOD)
        assert [stream.position for stream in draft.streams] == [1, 2]
        assert offers_of(draft) == [(GEO_OFFER, 100, "active")]
        assert draft.is_dirty is False

    async def test_tracks_non_offer_streams_without_parsing_their_offers(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        draft = await draft_service.load(campaign_id, PERIOD)
        geo = draft.streams[0]
        assert geo.holds_offers is False
        assert geo.offers == ()
        # Display-only details are still kept, which the reference tool drops.
        assert geo.countries == ("AU",)
        assert geo.redirect_url == "https://google.com"

    async def test_is_idempotent(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.sync(campaign_id)
        draft = await draft_service.load(campaign_id, PERIOD)
        assert len(draft.streams) == 2
        assert offers_of(draft) == [(GEO_OFFER, 100, "active")]

    async def test_records_the_fetch_time(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        draft = await draft_service.load(campaign_id, PERIOD)
        assert draft.last_synced_at is not None


class TestStagingChanges:
    async def test_added_offer_does_not_reach_keitaro(
        self, draft_service: CampaignDraftService, keitaro: FakeKeitaro, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)

        draft = await draft_service.load(campaign_id, PERIOD)
        assert offers_of(draft) == [(GEO_OFFER, 50, "active"), (EXTRA_OFFER, 50, "active")]
        assert draft.is_dirty is True
        # Keitaro still holds the old rotation.
        assert keitaro_offers(keitaro, campaign_id) == [(GEO_OFFER, 100)]

    async def test_removed_offer_does_not_reach_keitaro(
        self, draft_service: CampaignDraftService, keitaro: FakeKeitaro, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.remove_offer(campaign_id, GEO_OFFER)

        draft = await draft_service.load(campaign_id, PERIOD)
        assert offers_of(draft) == [(GEO_OFFER, 0, "removed")]
        assert draft.is_dirty is True
        assert keitaro_offers(keitaro, campaign_id) == [(GEO_OFFER, 100)]

    async def test_duplicate_offer_is_rejected(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        with pytest.raises(OfferAlreadyAttachedError):
            await draft_service.add_offer(campaign_id, GEO_OFFER)

    async def test_removing_twice_is_rejected(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.remove_offer(campaign_id, GEO_OFFER)
        with pytest.raises(OfferNotAttachedError):
            await draft_service.remove_offer(campaign_id, GEO_OFFER)

    async def test_shares_always_sum_to_one_hundred(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.add_offer(campaign_id, THIRD_OFFER)
        draft = await draft_service.load(campaign_id, PERIOD)
        assert sum(share for _, share, state in offers_of(draft) if state == "active") == 100


class TestPublish:
    async def test_pushes_the_draft(
        self, draft_service: CampaignDraftService, keitaro: FakeKeitaro, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.publish(campaign_id)

        assert keitaro_offers(keitaro, campaign_id) == [(GEO_OFFER, 50), (EXTRA_OFFER, 50)]
        draft = await draft_service.load(campaign_id, PERIOD)
        assert draft.is_dirty is False

    async def test_removed_offer_leaves_keitaro_but_stays_archived(
        self, draft_service: CampaignDraftService, keitaro: FakeKeitaro, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.publish(campaign_id)
        await draft_service.remove_offer(campaign_id, GEO_OFFER)
        await draft_service.publish(campaign_id)

        assert keitaro_offers(keitaro, campaign_id) == [(EXTRA_OFFER, 100)]
        draft = await draft_service.load(campaign_id, PERIOD)
        assert (GEO_OFFER, 0, "removed") in offers_of(draft)
        assert draft.is_dirty is False

    async def test_archived_offer_can_be_brought_back(
        self, draft_service: CampaignDraftService, keitaro: FakeKeitaro, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.publish(campaign_id)
        await draft_service.remove_offer(campaign_id, GEO_OFFER)
        await draft_service.publish(campaign_id)

        await draft_service.restore_offer(campaign_id, GEO_OFFER)
        assert (await draft_service.load(campaign_id, PERIOD)).is_dirty is True
        await draft_service.publish(campaign_id)
        assert sorted(keitaro_offers(keitaro, campaign_id)) == [
            (EXTRA_OFFER, 50),
            (GEO_OFFER, 50),
        ]

    async def test_nothing_to_publish(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        with pytest.raises(NothingToPublishError):
            await draft_service.publish(campaign_id)


class TestDiscard:
    async def test_drops_a_staged_addition(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.discard(campaign_id)

        draft = await draft_service.load(campaign_id, PERIOD)
        assert offers_of(draft) == [(GEO_OFFER, 100, "active")]
        assert draft.is_dirty is False

    async def test_undoes_a_staged_removal(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.remove_offer(campaign_id, GEO_OFFER)
        await draft_service.discard(campaign_id)

        draft = await draft_service.load(campaign_id, PERIOD)
        assert offers_of(draft) == [(GEO_OFFER, 100, "active")]
        assert draft.is_dirty is False

    async def test_keeps_published_state(
        self, draft_service: CampaignDraftService, keitaro: FakeKeitaro, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.publish(campaign_id)
        await draft_service.discard(campaign_id)

        draft = await draft_service.load(campaign_id, PERIOD)
        assert [offer_id for offer_id, _, state in offers_of(draft) if state == "active"] == [
            GEO_OFFER,
            EXTRA_OFFER,
        ]


class TestReconciliation:
    async def test_offer_deleted_in_keitaro_is_archived_not_lost(
        self, draft_service: CampaignDraftService, keitaro: FakeKeitaro, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.publish(campaign_id)

        # Somebody edits the campaign directly in Keitaro.
        stream = keitaro.offer_stream_of(campaign_id)
        assert stream is not None
        stream["offers"] = [{"offer_id": EXTRA_OFFER, "share": 100, "state": "active"}]

        await draft_service.sync(campaign_id)
        draft = await draft_service.load(campaign_id, PERIOD)
        assert (GEO_OFFER, 0, "removed") in offers_of(draft)
        assert draft.is_dirty is False

        await draft_service.restore_offer(campaign_id, GEO_OFFER)
        assert (await draft_service.load(campaign_id, PERIOD)).is_dirty is True

    async def test_offer_added_in_keitaro_shows_up(
        self, draft_service: CampaignDraftService, keitaro: FakeKeitaro, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        stream = keitaro.offer_stream_of(campaign_id)
        assert stream is not None
        stream["offers"].append({"offer_id": THIRD_OFFER, "share": 50, "state": "active"})
        stream["offers"][0]["share"] = 50

        await draft_service.sync(campaign_id)
        draft = await draft_service.load(campaign_id, PERIOD)
        assert (THIRD_OFFER, 50, "active") in offers_of(draft)
        assert draft.is_dirty is False

    async def test_fetch_keeps_unpublished_work(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.sync(campaign_id)

        draft = await draft_service.load(campaign_id, PERIOD)
        assert (EXTRA_OFFER, 50, "active") in offers_of(draft)
        assert draft.is_dirty is True


class TestPinnedShares:
    async def test_pinned_share_survives_a_recalculation(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.set_pin(campaign_id, GEO_OFFER, pinned=True, share=25)
        await draft_service.add_offer(campaign_id, THIRD_OFFER)

        draft = await draft_service.load(campaign_id, PERIOD)
        shares = {offer_id: share for offer_id, share, _ in offers_of(draft)}
        assert shares[GEO_OFFER] == 25
        assert shares[EXTRA_OFFER] + shares[THIRD_OFFER] == 75

    async def test_releasing_a_pin_rebalances_everything(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.set_pin(campaign_id, GEO_OFFER, pinned=True, share=25)
        await draft_service.set_pin(campaign_id, GEO_OFFER, pinned=False)

        draft = await draft_service.load(campaign_id, PERIOD)
        shares = {offer_id: share for offer_id, share, _ in offers_of(draft)}
        assert shares == {GEO_OFFER: 50, EXTRA_OFFER: 50}

    async def test_over_pinning_is_rejected(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.add_offer(campaign_id, EXTRA_OFFER)
        await draft_service.set_pin(campaign_id, GEO_OFFER, pinned=True, share=80)
        with pytest.raises(PinnedSharesExceededError):
            await draft_service.set_pin(campaign_id, EXTRA_OFFER, pinned=True, share=50)

    async def test_removed_offer_cannot_be_pinned(
        self, draft_service: CampaignDraftService, campaign_id: int
    ) -> None:
        await draft_service.sync(campaign_id)
        await draft_service.remove_offer(campaign_id, GEO_OFFER)
        with pytest.raises(OfferNotAttachedError):
            await draft_service.set_pin(campaign_id, GEO_OFFER, pinned=True, share=10)
