"""Campaign DTOs for the public API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from app.core.geo import country_name, normalize_country_code
from app.schemas.catalog import CampaignDefaultsOut
from app.schemas.common import ApiModel

CampaignName = Annotated[str, Field(min_length=1, max_length=200)]
PositiveId = Annotated[int, Field(gt=0, le=2_147_483_647)]
Share = Annotated[int, Field(ge=0, le=100)]


class CampaignCreateRequest(ApiModel):
    """Input of the campaign creator: name, geo code and Keitaro offer id."""

    name: CampaignName
    geo: Annotated[str, Field(min_length=2, max_length=2)]
    offer_id: PositiveId
    domain_id: PositiveId | None = None
    group_id: PositiveId | None = None
    source_id: PositiveId | None = None

    @field_validator("geo")
    @classmethod
    def _validate_geo(cls, value: str) -> str:
        code = normalize_country_code(value)
        if code is None:
            msg = "geo must be a valid ISO 3166-1 alpha-2 country code (e.g. AU, MX, RO)"
            raise ValueError(msg)
        return code


class StreamOut(ApiModel):
    id: int
    name: str
    schema_name: str | None = None
    position: int | None = None
    state: str | None = None
    redirect_url: str | None = None
    countries: list[str] = Field(default_factory=list)
    holds_offers: bool = False


class MetricsOut(ApiModel):
    clicks: int = 0
    unique_clicks: int = 0
    conversions: int = 0
    leads: int = 0
    sales: int = 0
    rejected: int = 0
    revenue: float = 0.0
    cost: float = 0.0
    profit: float = 0.0
    roi: float = 0.0
    cr: float = 0.0
    epc: float = 0.0


class CampaignSummaryOut(ApiModel):
    id: int
    name: str
    alias: str | None = None
    state: str | None = None
    group_id: int | None = None
    source_id: int | None = None
    domain_id: int | None = None


class CampaignCreateResponse(ApiModel):
    campaign: CampaignSummaryOut
    tracking_url: str | None
    geo: str
    geo_name: str
    redirect_url: str
    offer_id: int
    offer_name: str
    defaults: CampaignDefaultsOut
    streams: list[StreamOut]

    @classmethod
    def geo_label(cls, code: str) -> str:
        return country_name(code)


class PeriodOut(ApiModel):
    date_from: str
    date_to: str


class OfferAttachRequest(ApiModel):
    offer_id: PositiveId


class PinRequest(ApiModel):
    """Pin an offer's share so later recalculations leave it alone."""

    pinned: bool
    share: Share | None = None


# -- draft model ----------------------------------------------------------
class DraftOfferOut(ApiModel):
    offer_id: int
    name: str
    share: int
    synced_share: int
    pinned: bool
    state: Literal["active", "removed"]
    synced_state: Literal["absent", "active", "removed"]
    is_dirty: bool
    url: str | None = None
    metrics: MetricsOut


class DraftStreamOut(ApiModel):
    id: int
    name: str
    schema_name: str | None = None
    position: int
    state: str | None = None
    holds_offers: bool
    redirect_url: str | None = None
    countries: list[str] = Field(default_factory=list)
    offers: list[DraftOfferOut] = Field(default_factory=list)
    is_dirty: bool


class CampaignDraftResponse(ApiModel):
    """The editor's working copy of a campaign."""

    campaign_id: int
    name: str
    alias: str | None = None
    last_synced_at: str | None = None
    is_dirty: bool
    streams: list[DraftStreamOut]
    totals: MetricsOut
    stats_available: bool
    period: PeriodOut
