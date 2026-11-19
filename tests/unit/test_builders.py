"""Keitaro payload builders."""

from __future__ import annotations

import pytest
from app.keitaro import builders


class TestDistributeShares:
    @pytest.mark.parametrize(
        ("count", "expected"),
        [(0, []), (1, [100]), (2, [50, 50]), (3, [34, 33, 33]), (4, [25, 25, 25, 25])],
    )
    def test_shares(self, count: int, expected: list[int]) -> None:
        assert builders.distribute_shares(count) == expected

    @pytest.mark.parametrize("count", range(1, 25))
    def test_shares_always_sum_to_one_hundred(self, count: int) -> None:
        assert sum(builders.distribute_shares(count)) == 100


class TestCampaignPayload:
    def test_contains_domain_group_and_source(self) -> None:
        payload = builders.build_campaign_payload(
            name="test_ivanov_c1", domain_id=11, group_id=2, source_id=22
        )
        assert payload["name"] == "test_ivanov_c1"
        assert payload["domain_id"] == 11
        assert payload["group_id"] == 2
        assert payload["traffic_source_id"] == 22

    def test_generates_a_unique_alias(self) -> None:
        """Keitaro requires an alias and does not generate one itself."""
        aliases = {
            builders.build_campaign_payload(
                name="c", domain_id=1, group_id=1, source_id=1
            )["alias"]
            for _ in range(50)
        }
        assert len(aliases) == 50
        assert all(alias.isalnum() and len(alias) == 10 for alias in aliases)

    def test_accepts_an_explicit_alias(self) -> None:
        payload = builders.build_campaign_payload(
            name="c", domain_id=1, group_id=1, source_id=1, alias="fixed123"
        )
        assert payload["alias"] == "fixed123"

    def test_rotates_streams_by_position(self) -> None:
        payload = builders.build_campaign_payload(
            name="c", domain_id=1, group_id=1, source_id=1
        )
        assert payload["type"] == builders.ROTATION_BY_POSITION
        assert payload["state"] == "active"
        assert payload["cost_auto"] is True


class TestGeoRedirectStream:
    def test_filters_on_uppercase_country(self) -> None:
        payload = builders.build_geo_redirect_stream_payload(
            campaign_id=7, country_code="au", redirect_url="https://google.com"
        )
        assert payload["filters"] == [
            {"name": "country", "mode": "accept", "payload": ["AU"]}
        ]

    def test_redirects_to_the_given_url(self) -> None:
        payload = builders.build_geo_redirect_stream_payload(
            campaign_id=7, country_code="MX", redirect_url="https://google.com"
        )
        assert payload["schema"] == builders.SCHEMA_REDIRECT
        assert payload["action_type"] == builders.ACTION_HTTP_REDIRECT
        assert payload["action_payload"] == "https://google.com"

    def test_comes_before_the_offer_stream(self) -> None:
        geo = builders.build_geo_redirect_stream_payload(
            campaign_id=1, country_code="AU", redirect_url="https://google.com"
        )
        offers = builders.build_offer_stream_payload(campaign_id=1, offer_ids=[1])
        assert geo["position"] < offers["position"]


class TestOfferStream:
    def test_holds_offers_with_even_shares(self) -> None:
        payload = builders.build_offer_stream_payload(campaign_id=1, offer_ids=[10, 20])
        assert payload["schema"] == builders.SCHEMA_LANDINGS
        assert payload["offers"] == [
            {"offer_id": 10, "share": 50, "state": "active"},
            {"offer_id": 20, "share": 50, "state": "active"},
        ]

    def test_always_sends_an_action_type(self) -> None:
        """Keitaro rejects a stream without one, whatever the schema."""
        payload = builders.build_offer_stream_payload(campaign_id=1, offer_ids=[10])
        assert payload["action_type"] == builders.ACTION_HTTP_REDIRECT
        assert payload["action_payload"] == ""

    def test_empty_offer_list_is_allowed(self) -> None:
        payload = builders.build_offer_stream_payload(campaign_id=1, offer_ids=[])
        assert payload["offers"] == []


class TestReportPayload:
    def test_filters_by_campaign_and_groups_as_requested(self) -> None:
        payload = builders.build_report_payload(
            campaign_ids=[42], date_from="2026-01-01", date_to="2026-01-31", grouping="offer_id"
        )
        assert payload["grouping"] == ["offer_id"]
        assert payload["range"] == {
            "from": "2026-01-01",
            "to": "2026-01-31",
            "timezone": "UTC",
        }
        assert payload["filters"][0]["expression"] == ["42"]
