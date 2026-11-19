"""End-to-end API behaviour for the creator and the editor."""

from __future__ import annotations

import httpx
import pytest
from app.core.container import Container
from app.db.models import AuditAction, AuditLogEntry, CampaignRecord
from sqlalchemy import select

from tests.fakes import FakeKeitaro

NEW_CAMPAIGN = {"name": "campaign1", "geo": "AU", "offer_id": 4100}


async def create_campaign(client: httpx.AsyncClient, **overrides: object) -> dict:
    response = await client.post("/api/v1/campaigns", json={**NEW_CAMPAIGN, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


class TestCreateCampaign:
    async def test_creates_a_campaign_with_two_streams(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        body = await create_campaign(auth_client)
        assert body["campaign"]["name"] == "test_ivanov_campaign1"
        assert len(body["streams"]) == 2
        assert body["streams"][0]["countries"] == ["AU"]
        assert body["streams"][0]["redirect_url"] == "https://google.com"
        assert body["streams"][1]["holds_offers"] is True

    async def test_reports_domain_group_and_source(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        body = await create_campaign(auth_client)
        assert body["defaults"]["domain_name"] == "in.posdk.xyz"
        assert body["defaults"]["group_id"] > 0
        assert body["defaults"]["source_id"] > 0

    async def test_returns_a_tracking_url(self, auth_client: httpx.AsyncClient) -> None:
        body = await create_campaign(auth_client)
        assert body["tracking_url"].startswith("https://in.posdk.xyz/")

    async def test_resolves_the_country_name(self, auth_client: httpx.AsyncClient) -> None:
        body = await create_campaign(auth_client, geo="mx")
        assert body["geo"] == "MX"
        assert body["geo_name"] == "Mexico"

    async def test_stores_a_local_record_and_audit_entry(
        self, auth_client: httpx.AsyncClient, container: Container
    ) -> None:
        body = await create_campaign(auth_client)
        async with container.session_factory() as session:
            record = await session.scalar(
                select(CampaignRecord).where(
                    CampaignRecord.keitaro_id == body["campaign"]["id"]
                )
            )
            actions = (await session.scalars(select(AuditLogEntry.action))).all()
        assert record is not None
        assert record.geo == "AU"
        assert AuditAction.CAMPAIGN_CREATED in actions

    async def test_accepts_explicit_domain_group_and_source(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        body = await create_campaign(auth_client, domain_id=12, group_id=2, source_id=22)
        assert body["defaults"]["domain_id"] == 12
        assert body["defaults"]["group_id"] == 2
        assert body["defaults"]["source_id"] == 22

    @pytest.mark.parametrize(
        "payload",
        [
            {"geo": "AU", "offer_id": 4100},  # no name
            {"name": "c", "offer_id": 4100},  # no geo
            {"name": "c", "geo": "AU"},  # no offer
            {"name": "c", "geo": "XX", "offer_id": 4100},  # unknown country
            {"name": "c", "geo": "AUS", "offer_id": 4100},  # malformed country
            {"name": "c", "geo": "AU", "offer_id": 0},  # invalid id
            {"name": "c", "geo": "AU", "offer_id": -5},
            {"name": "c", "geo": "AU", "offer_id": 4100, "surprise": 1},  # unknown field
        ],
    )
    async def test_rejects_invalid_payloads(
        self, auth_client: httpx.AsyncClient, payload: dict
    ) -> None:
        response = await auth_client.post("/api/v1/campaigns", json=payload)
        assert response.status_code == 422

    async def test_unknown_offer_gives_404(self, auth_client: httpx.AsyncClient) -> None:
        response = await auth_client.post(
            "/api/v1/campaigns", json={**NEW_CAMPAIGN, "offer_id": 123456}
        )
        assert response.status_code == 404

    async def test_requires_authentication(self, client: httpx.AsyncClient) -> None:
        assert (await client.post("/api/v1/campaigns", json=NEW_CAMPAIGN)).status_code == 401

    async def test_upstream_failure_is_not_leaked(
        self, auth_client: httpx.AsyncClient, keitaro: FakeKeitaro
    ) -> None:
        keitaro.fail_stream_creation = True
        response = await auth_client.post("/api/v1/campaigns", json=NEW_CAMPAIGN)
        assert response.status_code == 503
        assert "Traceback" not in response.text


class TestCampaignListing:
    async def test_unknown_campaign_draft_gives_404(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        response = await auth_client.get("/api/v1/campaigns/999999/draft")
        assert response.status_code == 404

    @pytest.mark.parametrize("campaign_id", ["0", "-1", "abc"])
    async def test_rejects_malformed_ids(
        self, auth_client: httpx.AsyncClient, campaign_id: str
    ) -> None:
        response = await auth_client.get(f"/api/v1/campaigns/{campaign_id}/draft")
        assert response.status_code == 422

    async def test_a_new_campaign_is_listed_immediately(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        """Creating must invalidate the cached campaign list."""
        listed_before = (await auth_client.get("/api/v1/campaigns")).json()
        created = await create_campaign(auth_client, name="fresh")
        listed_after = (await auth_client.get("/api/v1/campaigns")).json()
        assert len(listed_after) == len(listed_before) + 1
        assert created["campaign"]["id"] in [c["id"] for c in listed_after]

    async def test_listing_filters_by_name(self, auth_client: httpx.AsyncClient) -> None:
        await create_campaign(auth_client, name="alpha")
        await create_campaign(auth_client, name="beta")
        response = await auth_client.get("/api/v1/campaigns", params={"q": "alpha"})
        names = [campaign["name"] for campaign in response.json()]
        assert names == ["test_ivanov_alpha"]


class TestEditorDraft:
    """The editor fetches into a draft and only publishes on demand."""

    @staticmethod
    def offers(body: dict) -> list[tuple[int, int, str]]:
        stream = next(s for s in body["streams"] if s["holds_offers"])
        return [(o["offer_id"], o["share"], o["state"]) for o in stream["offers"]]

    async def fetch(self, client: httpx.AsyncClient, campaign_id: int) -> dict:
        response = await client.post(f"/api/v1/campaigns/{campaign_id}/fetch")
        assert response.status_code == 200, response.text
        return response.json()

    async def test_draft_requires_a_fetch_first(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        created = await create_campaign(auth_client)
        response = await auth_client.get(
            f"/api/v1/campaigns/{created['campaign']['id']}/draft"
        )
        assert response.status_code == 404
        assert response.json()["code"] == "campaign_not_tracked"

    async def test_fetch_pulls_streams_and_offers(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        created = await create_campaign(auth_client)
        body = await self.fetch(auth_client, created["campaign"]["id"])
        assert [stream["position"] for stream in body["streams"]] == [1, 2]
        assert body["streams"][0]["countries"] == ["AU"]
        assert self.offers(body) == [(4100, 100, "active")]
        assert body["is_dirty"] is False

    async def test_adding_an_offer_does_not_touch_keitaro(
        self, auth_client: httpx.AsyncClient, keitaro: FakeKeitaro
    ) -> None:
        created = await create_campaign(auth_client)
        campaign_id = created["campaign"]["id"]
        await self.fetch(auth_client, campaign_id)

        response = await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers", json={"offer_id": 3749}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_dirty"] is True
        assert self.offers(body) == [(4100, 50, "active"), (3749, 50, "active")]

        stream = keitaro.offer_stream_of(campaign_id)
        assert stream is not None
        assert [o["offer_id"] for o in stream["offers"]] == [4100]

    async def test_publish_pushes_to_keitaro(
        self, auth_client: httpx.AsyncClient, keitaro: FakeKeitaro
    ) -> None:
        created = await create_campaign(auth_client)
        campaign_id = created["campaign"]["id"]
        await self.fetch(auth_client, campaign_id)
        await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers", json={"offer_id": 3749}
        )

        response = await auth_client.post(f"/api/v1/campaigns/{campaign_id}/publish")
        assert response.status_code == 200
        assert response.json()["is_dirty"] is False

        stream = keitaro.offer_stream_of(campaign_id)
        assert stream is not None
        assert [(o["offer_id"], o["share"]) for o in stream["offers"]] == [
            (4100, 50),
            (3749, 50),
        ]

    async def test_discard_rolls_the_draft_back(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        created = await create_campaign(auth_client)
        campaign_id = created["campaign"]["id"]
        await self.fetch(auth_client, campaign_id)
        await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers", json={"offer_id": 3749}
        )

        response = await auth_client.post(f"/api/v1/campaigns/{campaign_id}/discard")
        assert response.status_code == 200
        body = response.json()
        assert body["is_dirty"] is False
        assert self.offers(body) == [(4100, 100, "active")]

    async def test_removed_offer_stays_in_the_archive(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        created = await create_campaign(auth_client)
        campaign_id = created["campaign"]["id"]
        await self.fetch(auth_client, campaign_id)
        await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers", json={"offer_id": 3749}
        )
        await auth_client.post(f"/api/v1/campaigns/{campaign_id}/publish")

        removed = await auth_client.delete(f"/api/v1/campaigns/{campaign_id}/offers/4100")
        assert removed.status_code == 200
        assert (4100, 0, "removed") in self.offers(removed.json())

        restored = await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers/4100/restore"
        )
        assert restored.status_code == 200
        assert (4100, 50, "active") in self.offers(restored.json())

    async def test_pinned_share_survives_a_new_offer(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        created = await create_campaign(auth_client)
        campaign_id = created["campaign"]["id"]
        await self.fetch(auth_client, campaign_id)
        await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers", json={"offer_id": 3749}
        )
        pinned = await auth_client.put(
            f"/api/v1/campaigns/{campaign_id}/offers/4100/pin",
            json={"pinned": True, "share": 25},
        )
        assert pinned.status_code == 200

        await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers", json={"offer_id": 3717}
        )
        body = (await auth_client.get(f"/api/v1/campaigns/{campaign_id}/draft")).json()
        shares = {offer_id: share for offer_id, share, _ in self.offers(body)}
        assert shares[4100] == 25
        assert sum(shares.values()) == 100

    async def test_publishing_without_changes_is_rejected(
        self, auth_client: httpx.AsyncClient
    ) -> None:
        created = await create_campaign(auth_client)
        campaign_id = created["campaign"]["id"]
        await self.fetch(auth_client, campaign_id)
        response = await auth_client.post(f"/api/v1/campaigns/{campaign_id}/publish")
        assert response.status_code == 409
        assert response.json()["code"] == "nothing_to_publish"

    async def test_duplicate_offer_is_rejected(self, auth_client: httpx.AsyncClient) -> None:
        created = await create_campaign(auth_client)
        campaign_id = created["campaign"]["id"]
        await self.fetch(auth_client, campaign_id)
        response = await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers", json={"offer_id": 4100}
        )
        assert response.status_code == 409

    async def test_editor_actions_are_audited(
        self, auth_client: httpx.AsyncClient, container: Container
    ) -> None:
        created = await create_campaign(auth_client)
        campaign_id = created["campaign"]["id"]
        await self.fetch(auth_client, campaign_id)
        await auth_client.post(
            f"/api/v1/campaigns/{campaign_id}/offers", json={"offer_id": 3749}
        )
        await auth_client.post(f"/api/v1/campaigns/{campaign_id}/publish")

        async with container.session_factory() as session:
            actions = set((await session.scalars(select(AuditLogEntry.action))).all())
        assert {
            AuditAction.CAMPAIGN_SYNCED,
            AuditAction.OFFER_ATTACHED,
            AuditAction.DRAFT_PUBLISHED,
        } <= actions

    async def test_editing_requires_authentication(
        self, client: httpx.AsyncClient
    ) -> None:
        assert (await client.post("/api/v1/campaigns/1/fetch")).status_code == 401
        assert (await client.get("/api/v1/campaigns/1/draft")).status_code == 401


class TestCatalogEndpoints:
    async def test_offers_autocomplete(self, auth_client: httpx.AsyncClient) -> None:
        response = await auth_client.get("/api/v1/offers", params={"q": "keto"})
        assert [offer["id"] for offer in response.json()] == [4100]

    async def test_countries_are_served(self, auth_client: httpx.AsyncClient) -> None:
        countries = (await auth_client.get("/api/v1/countries")).json()
        assert {"code": "AU", "name": "Australia"} in countries

    async def test_campaign_defaults(self, auth_client: httpx.AsyncClient) -> None:
        body = (await auth_client.get("/api/v1/campaign-defaults")).json()
        assert body["domain_name"] == "in.posdk.xyz"

    async def test_catalog_requires_authentication(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/v1/offers")).status_code == 401
