"""Typed facade over the Keitaro Admin API.

Translates between our domain models and raw JSON, and is the only place that
knows Keitaro's URL layout.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import ValidationError

from app.core.exceptions import KeitaroError
from app.core.logging import get_logger
from app.keitaro.builders import CAMPAIGN_GROUP_TYPE
from app.keitaro.client import KeitaroClient
from app.keitaro.models import (
    Campaign,
    Domain,
    Group,
    KeitaroModel,
    Offer,
    Stream,
    TrafficSource,
)

logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=KeitaroModel)


class KeitaroGateway:
    """Implements :class:`~app.keitaro.protocols.KeitaroPort`."""

    def __init__(self, client: KeitaroClient) -> None:
        self._client = client

    # -- catalog -----------------------------------------------------------
    async def list_offers(self) -> list[Offer]:
        return self._parse_many(Offer, await self._client.get("/offers"))

    async def list_groups(self) -> list[Group]:
        # Keitaro requires the group type; campaign groups are "campaigns".
        params = {"type": CAMPAIGN_GROUP_TYPE}
        return self._parse_many(Group, await self._client.get("/groups", params=params))

    async def list_domains(self) -> list[Domain]:
        return self._parse_many(Domain, await self._client.get("/domains"))

    async def list_traffic_sources(self) -> list[TrafficSource]:
        return self._parse_many(TrafficSource, await self._client.get("/traffic_sources"))

    # -- campaigns ---------------------------------------------------------
    async def list_campaigns(self) -> list[Campaign]:
        return self._parse_many(Campaign, await self._client.get("/campaigns"))

    async def get_campaign(self, campaign_id: int) -> Campaign:
        path = f"/campaigns/{self._as_id(campaign_id)}"
        return self._parse_one(Campaign, await self._client.get(path))

    async def create_campaign(self, payload: dict[str, Any]) -> Campaign:
        return self._parse_one(Campaign, await self._client.post("/campaigns", json=payload))

    async def delete_campaign(self, campaign_id: int) -> None:
        await self._client.delete(f"/campaigns/{self._as_id(campaign_id)}")

    async def list_streams(self, campaign_id: int) -> list[Stream]:
        path = f"/campaigns/{self._as_id(campaign_id)}/streams"
        return self._parse_many(Stream, await self._client.get(path))

    # -- streams -----------------------------------------------------------
    async def create_stream(self, payload: dict[str, Any]) -> Stream:
        return self._parse_one(Stream, await self._client.post("/streams", json=payload))

    async def update_stream(self, stream_id: int, payload: dict[str, Any]) -> Stream:
        path = f"/streams/{self._as_id(stream_id)}"
        return self._parse_one(Stream, await self._client.put(path, json=payload))

    async def delete_stream(self, stream_id: int) -> None:
        await self._client.delete(f"/streams/{self._as_id(stream_id)}")

    # -- reports -----------------------------------------------------------
    async def build_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = await self._client.post("/report/build", json=payload)
        if not isinstance(body, dict):
            raise KeitaroError(detail="Unexpected report payload shape")
        return body

    # -- parsing helpers ---------------------------------------------------
    @staticmethod
    def _as_id(value: int) -> int:
        """Validate an identifier before it becomes part of a URL path."""
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            msg = f"Invalid Keitaro identifier: {value!r}"
            raise ValueError(msg)
        return value

    @staticmethod
    def _parse_one(model: type[ModelT], body: Any) -> ModelT:
        try:
            return model.model_validate(body)
        except ValidationError as exc:
            logger.error("Cannot parse %s from Keitaro: %s", model.__name__, exc.error_count())
            raise KeitaroError(detail=f"Unexpected {model.__name__} payload") from exc

    @staticmethod
    def _parse_many(model: type[ModelT], body: Any) -> list[ModelT]:
        if body is None:
            return []
        if not isinstance(body, list):
            raise KeitaroError(detail=f"Expected a list of {model.__name__}")
        parsed: list[ModelT] = []
        for item in body:
            try:
                parsed.append(model.model_validate(item))
            except ValidationError:
                # One malformed row must not break the whole listing.
                logger.warning("Skipping unparsable %s row from Keitaro", model.__name__)
        return parsed
