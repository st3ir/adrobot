"""Pydantic models for the Keitaro Admin API payloads.

Keitaro returns a lot of fields we do not care about and adds new ones between
releases, so every model ignores unknown keys and keeps all non-essential
fields optional. That makes the wrapper resilient to upstream changes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StreamSchema = Literal["landings", "action", "redirect", "position"]
StreamType = Literal["regular", "forced", "default"]
EntityState = Literal["active", "disabled", "deleted"]


class KeitaroModel(BaseModel):
    """Base model: forgiving on input, strict on our own field names."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)


class Group(KeitaroModel):
    id: int
    name: str
    # "campaign" | "offer" | "landing"
    type: str | None = None


class Domain(KeitaroModel):
    id: int
    name: str
    state: str | None = None
    campaign_id: int | None = None
    catch_not_found: int | bool | None = None
    ssl_redirect: int | bool | None = None


class TrafficSource(KeitaroModel):
    id: int
    name: str
    state: str | None = None


class Offer(KeitaroModel):
    id: int
    name: str
    group_id: int | None = None
    offer_group_id: int | None = None
    action_payload: str | None = None
    country: str | list[str] | None = None
    state: str | None = None
    archive: int | bool | None = None
    payout_value: float | None = None
    payout_currency: str | None = None
    affiliate_network_id: int | None = None

    @property
    def is_archived(self) -> bool:
        return bool(self.archive)


class StreamOffer(KeitaroModel):
    """An offer slot inside a stream (``schema="landings"``)."""

    offer_id: int
    share: int = 100
    state: EntityState = "active"
    id: int | None = None
    name: str | None = None


class StreamFilter(KeitaroModel):
    """A single stream filter, e.g. country acceptance."""

    name: str
    mode: Literal["accept", "reject"] = "accept"
    payload: Any = None


class Stream(KeitaroModel):
    id: int
    campaign_id: int | None = None
    name: str | None = None
    type: StreamType | None = None
    schema_: str | None = Field(default=None, alias="schema")
    action_type: str | None = None
    action_payload: str | None = None
    position: int | None = None
    weight: int | None = None
    state: str | None = None
    comments: str | None = None
    collect_clicks: int | bool | None = None
    filter_or: int | bool | None = None
    filters: tuple[StreamFilter, ...] = ()
    offers: tuple[StreamOffer, ...] = ()
    landings: tuple[dict[str, Any], ...] = ()

    @field_validator("filters", "offers", "landings", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        return () if value is None else value

    @property
    def holds_offers(self) -> bool:
        """True when this stream can carry offers."""
        return self.schema_ == "landings"

    @property
    def active_offers(self) -> tuple[StreamOffer, ...]:
        return tuple(offer for offer in self.offers if offer.state != "deleted")


class Campaign(KeitaroModel):
    id: int
    name: str
    alias: str | None = None
    state: str | None = None
    type: str | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None
    domain_id: int | None = None
    token: str | None = None
    cost_type: str | None = None
    cost_value: float | None = None
    cost_currency: str | None = None
    cost_auto: int | bool | None = None
    position: int | None = None
    streams: tuple[Stream, ...] = ()

    @field_validator("streams", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        return () if value is None else value
