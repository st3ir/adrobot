"""Gateway: URL layout, JSON parsing and defensive behaviour."""

from __future__ import annotations

import httpx
import pytest
import respx
from app.core.exceptions import KeitaroError
from app.keitaro.client import KeitaroClient
from app.keitaro.gateway import KeitaroGateway

API_ROOT = "https://keitaro.test/admin_api/v1"


@pytest.fixture
async def gateway():
    client = KeitaroClient(api_root=API_ROOT, api_key="k", max_retries=0)
    try:
        yield KeitaroGateway(client)
    finally:
        await client.aclose()


class TestCatalogEndpoints:
    @respx.mock
    async def test_offers(self, gateway: KeitaroGateway) -> None:
        respx.get(f"{API_ROOT}/offers").mock(
            httpx.Response(200, json=[{"id": 1, "name": "Offer", "unknown_field": "ignored"}])
        )
        offers = await gateway.list_offers()
        assert offers[0].id == 1
        assert offers[0].name == "Offer"

    @respx.mock
    async def test_domains_groups_and_sources_use_their_own_paths(
        self, gateway: KeitaroGateway
    ) -> None:
        for path, call in (
            ("domains", gateway.list_domains),
            ("groups", gateway.list_groups),
            ("traffic_sources", gateway.list_traffic_sources),
        ):
            route = respx.get(f"{API_ROOT}/{path}").mock(
                httpx.Response(200, json=[{"id": 1, "name": "x"}])
            )
            assert len(await call()) == 1
            assert route.called

    @respx.mock
    async def test_a_malformed_row_does_not_break_the_listing(
        self, gateway: KeitaroGateway
    ) -> None:
        respx.get(f"{API_ROOT}/offers").mock(
            httpx.Response(200, json=[{"id": 1, "name": "ok"}, {"name": "no id"}])
        )
        assert [offer.id for offer in await gateway.list_offers()] == [1]

    @respx.mock
    async def test_null_body_becomes_an_empty_list(self, gateway: KeitaroGateway) -> None:
        respx.get(f"{API_ROOT}/offers").mock(httpx.Response(200, json=None))
        assert await gateway.list_offers() == []

    @respx.mock
    async def test_an_object_where_a_list_is_expected_is_an_error(
        self, gateway: KeitaroGateway
    ) -> None:
        respx.get(f"{API_ROOT}/offers").mock(httpx.Response(200, json={"id": 1}))
        with pytest.raises(KeitaroError):
            await gateway.list_offers()


class TestCampaignsAndStreams:
    @respx.mock
    async def test_create_campaign_posts_the_payload(self, gateway: KeitaroGateway) -> None:
        route = respx.post(f"{API_ROOT}/campaigns").mock(
            httpx.Response(200, json={"id": 7, "name": "c", "alias": "a7"})
        )
        campaign = await gateway.create_campaign({"name": "c"})
        assert campaign.id == 7
        assert route.calls.last.request.read() == b'{"name":"c"}'

    @respx.mock
    async def test_streams_are_read_from_the_campaign_subresource(
        self, gateway: KeitaroGateway
    ) -> None:
        route = respx.get(f"{API_ROOT}/campaigns/7/streams").mock(
            httpx.Response(200, json=[{"id": 1, "schema": "landings", "offers": None}])
        )
        streams = await gateway.list_streams(7)
        assert route.called
        assert streams[0].schema_ == "landings"
        assert streams[0].offers == ()
        assert streams[0].holds_offers

    @respx.mock
    async def test_update_and_delete_stream(self, gateway: KeitaroGateway) -> None:
        respx.put(f"{API_ROOT}/streams/5").mock(httpx.Response(200, json={"id": 5}))
        delete_route = respx.delete(f"{API_ROOT}/streams/5").mock(httpx.Response(204))
        assert (await gateway.update_stream(5, {"offers": []})).id == 5
        await gateway.delete_stream(5)
        assert delete_route.called

    @respx.mock
    async def test_delete_campaign(self, gateway: KeitaroGateway) -> None:
        route = respx.delete(f"{API_ROOT}/campaigns/7").mock(httpx.Response(204))
        await gateway.delete_campaign(7)
        assert route.called

    @pytest.mark.parametrize("bad_id", [0, -1, True, "7"])
    async def test_identifiers_are_validated_before_they_reach_the_url(
        self, gateway: KeitaroGateway, bad_id: object
    ) -> None:
        with pytest.raises(ValueError, match="Invalid Keitaro identifier"):
            await gateway.get_campaign(bad_id)  # type: ignore[arg-type]

    @respx.mock
    async def test_unparsable_campaign_is_reported(self, gateway: KeitaroGateway) -> None:
        respx.get(f"{API_ROOT}/campaigns/7").mock(httpx.Response(200, json={"name": "no id"}))
        with pytest.raises(KeitaroError):
            await gateway.get_campaign(7)


class TestReports:
    @respx.mock
    async def test_build_report(self, gateway: KeitaroGateway) -> None:
        respx.post(f"{API_ROOT}/report/build").mock(
            httpx.Response(200, json={"rows": [{"clicks": 1}]})
        )
        assert await gateway.build_report({"grouping": ["campaign_id"]}) == {
            "rows": [{"clicks": 1}]
        }

    @respx.mock
    async def test_unexpected_report_shape(self, gateway: KeitaroGateway) -> None:
        respx.post(f"{API_ROOT}/report/build").mock(httpx.Response(200, json=[]))
        with pytest.raises(KeitaroError):
            await gateway.build_report({})
