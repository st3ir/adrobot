"""In-memory stand-in for the Keitaro Admin API.

Implements :class:`~app.keitaro.protocols.KeitaroPort` so the whole stack can
be exercised in tests without a tracker or network access.
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import KeitaroNotFoundError, KeitaroUnavailableError
from app.keitaro.models import Campaign, Domain, Group, Offer, Stream, TrafficSource

DEFAULT_OFFERS: list[dict[str, Any]] = [
    {
        "id": 3749,
        "name": "Miaflow [BEAUTY-RO-BE_0009]",
        "action_payload": "https://track.example/ro-9",
        "payout_value": 24.5,
        "payout_currency": "USD",
        "archive": 0,
    },
    {
        "id": 3717,
        "name": "Miaflow [BEAUTY-RO-BE_0008]",
        "action_payload": "https://track.example/ro-8",
        "payout_value": 21.0,
        "payout_currency": "USD",
        "archive": 0,
    },
    {
        "id": 4100,
        "name": "Keto Gummies AU",
        "action_payload": "https://track.example/au",
        "payout_value": 30.0,
        "payout_currency": "USD",
        "archive": 0,
    },
    {
        "id": 9001,
        "name": "Archived offer",
        "action_payload": "https://track.example/old",
        "archive": 1,
    },
]


class FakeKeitaro:
    """A tiny, deterministic Keitaro replica."""

    def __init__(self) -> None:
        self.offers_data = [dict(offer) for offer in DEFAULT_OFFERS]
        # Keitaro returns plural group types ("campaigns" / "offers").
        self.groups_data = [
            {"id": 1, "name": "DEFAULT", "type": "campaigns"},
            {"id": 2, "name": "FORTESTS", "type": "campaigns"},
            {"id": 3, "name": "OfferGroup", "type": "offers"},
        ]
        self.domains_data = [
            {"id": 11, "name": "in.posdk.xyz", "state": "active"},
            {"id": 12, "name": "second.example", "state": "active"},
        ]
        self.sources_data = [
            {"id": 21, "name": "DEFAULT"},
            {"id": 22, "name": "FORTESTS"},
        ]
        self.campaigns: dict[int, dict[str, Any]] = {}
        self.streams: dict[int, dict[str, Any]] = {}
        self.report_rows: dict[str, list[dict[str, Any]]] = {}

        self._next_campaign_id = 500
        self._next_stream_id = 9000

        #: Set to raise on the next stream creation (rollback tests).
        self.fail_stream_creation = False
        self.deleted_campaigns: list[int] = []
        self.report_fails = False

    # -- catalog -----------------------------------------------------------
    async def list_offers(self) -> list[Offer]:
        return [Offer.model_validate(item) for item in self.offers_data]

    async def list_groups(self) -> list[Group]:
        return [Group.model_validate(item) for item in self.groups_data]

    async def list_domains(self) -> list[Domain]:
        return [Domain.model_validate(item) for item in self.domains_data]

    async def list_traffic_sources(self) -> list[TrafficSource]:
        return [TrafficSource.model_validate(item) for item in self.sources_data]

    # -- campaigns ---------------------------------------------------------
    async def list_campaigns(self) -> list[Campaign]:
        return [Campaign.model_validate(item) for item in self.campaigns.values()]

    async def get_campaign(self, campaign_id: int) -> Campaign:
        try:
            return Campaign.model_validate(self.campaigns[campaign_id])
        except KeyError as exc:
            raise KeitaroNotFoundError from exc

    async def create_campaign(self, payload: dict[str, Any]) -> Campaign:
        self._next_campaign_id += 1
        campaign_id = self._next_campaign_id
        record = {
            **payload,
            "id": campaign_id,
            "alias": payload.get("alias") or f"alias{campaign_id}",
        }
        self.campaigns[campaign_id] = record
        return Campaign.model_validate(record)

    async def delete_campaign(self, campaign_id: int) -> None:
        self.campaigns.pop(campaign_id, None)
        self.deleted_campaigns.append(campaign_id)

    async def list_streams(self, campaign_id: int) -> list[Stream]:
        if campaign_id not in self.campaigns:
            raise KeitaroNotFoundError
        return [
            Stream.model_validate(item)
            for item in self.streams.values()
            if item.get("campaign_id") == campaign_id
        ]

    # -- streams -----------------------------------------------------------
    async def create_stream(self, payload: dict[str, Any]) -> Stream:
        if self.fail_stream_creation:
            raise KeitaroUnavailableError
        self._next_stream_id += 1
        stream_id = self._next_stream_id
        record = {**payload, "id": stream_id}
        self.streams[stream_id] = record
        return Stream.model_validate(record)

    async def update_stream(self, stream_id: int, payload: dict[str, Any]) -> Stream:
        try:
            record = self.streams[stream_id]
        except KeyError as exc:
            raise KeitaroNotFoundError from exc
        record.update(payload)
        return Stream.model_validate(record)

    async def delete_stream(self, stream_id: int) -> None:
        self.streams.pop(stream_id, None)

    # -- reports -----------------------------------------------------------
    async def build_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.report_fails:
            raise KeitaroUnavailableError
        grouping = (payload.get("grouping") or ["campaign_id"])[0]
        return {"rows": self.report_rows.get(grouping, [])}

    # -- helpers for assertions -------------------------------------------
    def streams_of(self, campaign_id: int) -> list[dict[str, Any]]:
        return sorted(
            (s for s in self.streams.values() if s.get("campaign_id") == campaign_id),
            key=lambda item: item.get("position", 0),
        )

    def offer_stream_of(self, campaign_id: int) -> dict[str, Any] | None:
        for stream in self.streams_of(campaign_id):
            if stream.get("schema") == "landings":
                return stream
        return None
