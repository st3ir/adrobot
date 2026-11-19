"""Catalog service: offer search and campaign defaults."""

from __future__ import annotations

import pytest
from app.core.exceptions import CatalogIncompleteError, KeitaroNotFoundError
from app.services.catalog import CatalogService

from tests.fakes import FakeKeitaro


@pytest.fixture
def catalog(keitaro: FakeKeitaro) -> CatalogService:
    return CatalogService(keitaro, ttl_seconds=0)


@pytest.fixture
def keitaro() -> FakeKeitaro:
    return FakeKeitaro()


class TestOfferSearch:
    async def test_hides_archived_offers(self, catalog: CatalogService) -> None:
        names = [offer.name for offer in await catalog.search_offers()]
        assert "Archived offer" not in names

    async def test_matches_by_name_fragment(self, catalog: CatalogService) -> None:
        found = await catalog.search_offers("keto")
        assert [offer.id for offer in found] == [4100]

    async def test_matches_by_id(self, catalog: CatalogService) -> None:
        found = await catalog.search_offers("3717")
        assert found[0].id == 3717

    async def test_prefix_matches_rank_first(self, catalog: CatalogService) -> None:
        found = await catalog.search_offers("miaflow")
        assert all(offer.name.lower().startswith("miaflow") for offer in found)

    async def test_respects_the_limit(self, catalog: CatalogService) -> None:
        assert len(await catalog.search_offers(limit=1)) == 1

    async def test_get_offer_raises_for_unknown_id(self, catalog: CatalogService) -> None:
        with pytest.raises(KeitaroNotFoundError):
            await catalog.get_offer(999999)


class TestCampaignSearch:
    async def test_lists_newest_first(
        self, catalog: CatalogService, keitaro: FakeKeitaro
    ) -> None:
        await keitaro.create_campaign({"name": "first"})
        await keitaro.create_campaign({"name": "second"})
        found = await catalog.search_campaigns()
        assert [campaign.name for campaign in found] == ["second", "first"]

    async def test_matches_by_name_and_id(
        self, catalog: CatalogService, keitaro: FakeKeitaro
    ) -> None:
        created = await keitaro.create_campaign({"name": "test_ivanov_alpha"})
        await keitaro.create_campaign({"name": "unrelated"})
        assert [c.id for c in await catalog.search_campaigns("alpha")] == [created.id]
        assert [c.id for c in await catalog.search_campaigns(str(created.id))] == [
            created.id
        ]

    async def test_respects_the_limit(
        self, catalog: CatalogService, keitaro: FakeKeitaro
    ) -> None:
        for index in range(5):
            await keitaro.create_campaign({"name": f"c{index}"})
        assert len(await catalog.search_campaigns(limit=2)) == 2


class TestCampaignDefaults:
    async def test_falls_back_to_the_first_entity(self, catalog: CatalogService) -> None:
        defaults = await catalog.resolve_campaign_defaults()
        assert (defaults.domain_id, defaults.group_id, defaults.source_id) == (11, 1, 21)

    async def test_prefers_configured_names(self, keitaro: FakeKeitaro) -> None:
        catalog = CatalogService(
            keitaro, ttl_seconds=0, preferred_group="FORTESTS", preferred_source="fortests"
        )
        defaults = await catalog.resolve_campaign_defaults()
        assert defaults.group_name == "FORTESTS"
        assert defaults.source_name == "FORTESTS"

    async def test_explicit_ids_win(self, catalog: CatalogService) -> None:
        defaults = await catalog.resolve_campaign_defaults(domain_id=12, source_id=22)
        assert defaults.domain_id == 12
        assert defaults.source_id == 22

    async def test_unknown_explicit_id_is_rejected(self, catalog: CatalogService) -> None:
        with pytest.raises(KeitaroNotFoundError):
            await catalog.resolve_campaign_defaults(domain_id=404)

    async def test_offer_groups_are_not_offered_as_campaign_groups(
        self, catalog: CatalogService
    ) -> None:
        defaults = await catalog.resolve_campaign_defaults(group_id=2)
        assert defaults.group_name == "FORTESTS"
        with pytest.raises(KeitaroNotFoundError):
            await catalog.resolve_campaign_defaults(group_id=3)  # an offer group

    async def test_empty_catalog_is_reported(self, keitaro: FakeKeitaro) -> None:
        keitaro.domains_data = []
        catalog = CatalogService(keitaro, ttl_seconds=0)
        with pytest.raises(CatalogIncompleteError):
            await catalog.resolve_campaign_defaults()


class TestCaching:
    async def test_offers_are_cached_within_the_ttl(self, keitaro: FakeKeitaro) -> None:
        calls = 0
        original = keitaro.list_offers

        async def counting():  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return await original()

        keitaro.list_offers = counting  # type: ignore[method-assign]
        catalog = CatalogService(keitaro, ttl_seconds=60)
        await catalog.search_offers()
        await catalog.search_offers()
        assert calls == 1

        catalog.invalidate()
        await catalog.search_offers()
        assert calls == 2
