"""Campaign creation use case."""

from __future__ import annotations

import pytest
from app.core.exceptions import KeitaroNotFoundError, KeitaroUnavailableError
from app.services.campaign_creator import CampaignCreateCommand, CampaignCreatorService
from app.services.catalog import CatalogService
from app.services.naming import InvalidCampaignNameError

from tests.fakes import FakeKeitaro


@pytest.fixture
def keitaro() -> FakeKeitaro:
    return FakeKeitaro()


@pytest.fixture
def creator(keitaro: FakeKeitaro) -> CampaignCreatorService:
    return CampaignCreatorService(
        campaigns=keitaro,
        streams=keitaro,
        catalog=CatalogService(keitaro, ttl_seconds=0, preferred_group="FORTESTS"),
        name_prefix="test_ivanov_",
        redirect_url="https://google.com",
    )


COMMAND = CampaignCreateCommand(name="campaign1", geo="AU", offer_id=4100)


class TestCreate:
    async def test_creates_a_campaign_with_the_team_prefix(
        self, creator: CampaignCreatorService
    ) -> None:
        result = await creator.create(COMMAND)
        assert result.campaign.name == "test_ivanov_campaign1"

    async def test_creates_exactly_two_streams(
        self, creator: CampaignCreatorService, keitaro: FakeKeitaro
    ) -> None:
        result = await creator.create(COMMAND)
        streams = keitaro.streams_of(result.campaign.id)
        assert len(streams) == 2

    async def test_first_stream_catches_the_geo_and_redirects(
        self, creator: CampaignCreatorService, keitaro: FakeKeitaro
    ) -> None:
        result = await creator.create(COMMAND)
        geo_stream = keitaro.streams_of(result.campaign.id)[0]
        assert geo_stream["position"] == 1
        assert geo_stream["action_payload"] == "https://google.com"
        assert geo_stream["filters"] == [
            {"name": "country", "mode": "accept", "payload": ["AU"]}
        ]

    async def test_second_stream_sends_everyone_else_to_the_offer(
        self, creator: CampaignCreatorService, keitaro: FakeKeitaro
    ) -> None:
        result = await creator.create(COMMAND)
        offer_stream = keitaro.streams_of(result.campaign.id)[1]
        assert offer_stream["position"] == 2
        assert offer_stream["offers"] == [
            {"offer_id": 4100, "share": 100, "state": "active"}
        ]
        assert not offer_stream.get("filters")

    async def test_configures_domain_group_and_source(
        self, creator: CampaignCreatorService, keitaro: FakeKeitaro
    ) -> None:
        result = await creator.create(COMMAND)
        record = keitaro.campaigns[result.campaign.id]
        assert record["domain_id"] == 11
        assert record["group_id"] == 2  # FORTESTS, as configured
        assert record["traffic_source_id"] == 21

    async def test_returns_the_tracking_url(self, creator: CampaignCreatorService) -> None:
        result = await creator.create(COMMAND)
        assert result.tracking_url == f"https://in.posdk.xyz/{result.campaign.alias}"

    async def test_geo_code_is_upper_cased(
        self, creator: CampaignCreatorService, keitaro: FakeKeitaro
    ) -> None:
        result = await creator.create(
            CampaignCreateCommand(name="c", geo="mx", offer_id=4100)
        )
        geo_stream = keitaro.streams_of(result.campaign.id)[0]
        assert geo_stream["filters"][0]["payload"] == ["MX"]


class TestValidation:
    async def test_rejects_an_unknown_offer(self, creator: CampaignCreatorService) -> None:
        with pytest.raises(KeitaroNotFoundError):
            await creator.create(CampaignCreateCommand(name="c", geo="AU", offer_id=1))

    async def test_rejects_an_empty_name(self, creator: CampaignCreatorService) -> None:
        with pytest.raises(InvalidCampaignNameError):
            await creator.create(CampaignCreateCommand(name="  ", geo="AU", offer_id=4100))

    async def test_nothing_is_created_when_the_offer_is_unknown(
        self, creator: CampaignCreatorService, keitaro: FakeKeitaro
    ) -> None:
        with pytest.raises(KeitaroNotFoundError):
            await creator.create(CampaignCreateCommand(name="c", geo="AU", offer_id=1))
        assert keitaro.campaigns == {}


class TestRollback:
    async def test_removes_the_campaign_when_a_stream_cannot_be_created(
        self, creator: CampaignCreatorService, keitaro: FakeKeitaro
    ) -> None:
        keitaro.fail_stream_creation = True
        with pytest.raises(KeitaroUnavailableError):
            await creator.create(COMMAND)
        assert keitaro.campaigns == {}
        assert keitaro.deleted_campaigns  # the half-built campaign was cleaned up
