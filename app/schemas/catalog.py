"""Reference data DTOs."""

from __future__ import annotations

from app.schemas.common import ApiModel


class OfferOut(ApiModel):
    id: int
    name: str
    url: str | None = None
    payout_value: float | None = None
    payout_currency: str | None = None


class NamedEntityOut(ApiModel):
    id: int
    name: str


class CountryOut(ApiModel):
    code: str
    name: str


class CampaignDefaultsOut(ApiModel):
    domain_id: int
    domain_name: str
    group_id: int
    group_name: str
    source_id: int
    source_name: str
