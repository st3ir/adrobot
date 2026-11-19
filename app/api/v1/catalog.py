"""Reference data endpoints used by the UI (offers autocomplete, defaults)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CatalogDep, CurrentUser
from app.core.geo import COUNTRIES
from app.schemas.catalog import (
    CampaignDefaultsOut,
    CountryOut,
    NamedEntityOut,
    OfferOut,
)

router = APIRouter(tags=["catalog"])


@router.get("/offers", response_model=list[OfferOut])
async def search_offers(
    catalog: CatalogDep,
    _: CurrentUser,
    q: Annotated[str, Query(max_length=120, description="Search by name or id")] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[OfferOut]:
    """Autocomplete over Keitaro offers."""
    offers = await catalog.search_offers(q, limit=limit)
    return [
        OfferOut(
            id=offer.id,
            name=offer.name,
            url=offer.action_payload,
            payout_value=offer.payout_value,
            payout_currency=offer.payout_currency,
        )
        for offer in offers
    ]


@router.get("/countries", response_model=list[CountryOut])
async def list_countries(_: CurrentUser) -> list[CountryOut]:
    """ISO 3166-1 alpha-2 codes accepted by the campaign creator."""
    return [CountryOut(code=code, name=name) for code, name in sorted(COUNTRIES.items())]


@router.get("/groups", response_model=list[NamedEntityOut])
async def list_groups(catalog: CatalogDep, _: CurrentUser) -> list[NamedEntityOut]:
    return [NamedEntityOut(id=item.id, name=item.name) for item in await catalog.groups()]


@router.get("/domains", response_model=list[NamedEntityOut])
async def list_domains(catalog: CatalogDep, _: CurrentUser) -> list[NamedEntityOut]:
    return [NamedEntityOut(id=item.id, name=item.name) for item in await catalog.domains()]


@router.get("/sources", response_model=list[NamedEntityOut])
async def list_sources(catalog: CatalogDep, _: CurrentUser) -> list[NamedEntityOut]:
    return [
        NamedEntityOut(id=item.id, name=item.name) for item in await catalog.traffic_sources()
    ]


@router.get("/campaign-defaults", response_model=CampaignDefaultsOut)
async def campaign_defaults(catalog: CatalogDep, _: CurrentUser) -> CampaignDefaultsOut:
    """Domain/group/source a new campaign would be created with."""
    defaults = await catalog.resolve_campaign_defaults()
    return CampaignDefaultsOut(
        domain_id=defaults.domain_id,
        domain_name=defaults.domain_name,
        group_id=defaults.group_id,
        group_name=defaults.group_name,
        source_id=defaults.source_id,
        source_name=defaults.source_name,
    )
