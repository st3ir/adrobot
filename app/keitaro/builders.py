"""Builders for Keitaro request payloads.

Every Keitaro-specific constant lives here, so adapting to an API change means
editing one small module instead of hunting through the service layer.
"""

from __future__ import annotations

import secrets
import string
from typing import Any, Final

# -- Keitaro vocabulary ----------------------------------------------------
#: Streams are evaluated top-down by position (campaign "Ротация потоков").
ROTATION_BY_POSITION: Final = "position"
#: A stream that redirects the visitor somewhere else.
SCHEMA_REDIRECT: Final = "redirect"
#: A stream that rotates landings/offers.
SCHEMA_LANDINGS: Final = "landings"
#: Action type for a plain HTTP redirect.
ACTION_HTTP_REDIRECT: Final = "http"
#: Stream filter that matches the visitor's country.
FILTER_COUNTRY: Final = "country"
#: Group type to ask for when listing campaign groups (note the plural).
CAMPAIGN_GROUP_TYPE: Final = "campaigns"

STREAM_TYPE_REGULAR: Final = "regular"
STATE_ACTIVE: Final = "active"
STATE_DELETED: Final = "deleted"

DEFAULT_COST_TYPE: Final = "CPC"
DEFAULT_COST_CURRENCY: Final = "USD"

#: Campaign alias = the path after the domain. Keitaro requires one and does
#: not generate it, so we do. 62**10 keeps collisions theoretical.
ALIAS_ALPHABET: Final = string.ascii_letters + string.digits
ALIAS_LENGTH: Final = 10

GEO_STREAM_POSITION: Final = 1
OFFER_STREAM_POSITION: Final = 2
TOTAL_SHARE: Final = 100


def generate_campaign_alias() -> str:
    """Return a random campaign alias (the URL path after the domain)."""
    return "".join(secrets.choice(ALIAS_ALPHABET) for _ in range(ALIAS_LENGTH))


def build_campaign_payload(
    *,
    name: str,
    domain_id: int,
    group_id: int,
    source_id: int,
    alias: str | None = None,
    cost_currency: str = DEFAULT_COST_CURRENCY,
) -> dict[str, Any]:
    """Payload for ``POST /admin_api/v1/campaigns``."""
    return {
        "name": name,
        "alias": alias or generate_campaign_alias(),
        "type": ROTATION_BY_POSITION,
        "state": STATE_ACTIVE,
        "cost_type": DEFAULT_COST_TYPE,
        "cost_value": 0,
        "cost_currency": cost_currency,
        "cost_auto": True,
        "domain_id": domain_id,
        "group_id": group_id,
        "traffic_source_id": source_id,
    }


def build_geo_redirect_stream_payload(
    *,
    campaign_id: int,
    country_code: str,
    redirect_url: str,
    position: int = GEO_STREAM_POSITION,
    name: str | None = None,
) -> dict[str, Any]:
    """Stream that catches one country and redirects it to ``redirect_url``."""
    geo = country_code.upper()
    return {
        "campaign_id": campaign_id,
        "name": name or f"GEO {geo} -> redirect",
        "type": STREAM_TYPE_REGULAR,
        "schema": SCHEMA_REDIRECT,
        "action_type": ACTION_HTTP_REDIRECT,
        "action_payload": redirect_url,
        "position": position,
        "weight": TOTAL_SHARE,
        "state": STATE_ACTIVE,
        "collect_clicks": True,
        "filter_or": False,
        "filters": [
            {"name": FILTER_COUNTRY, "mode": "accept", "payload": [geo]},
        ],
    }


def build_offer_stream_payload(
    *,
    campaign_id: int,
    offer_ids: list[int],
    position: int = OFFER_STREAM_POSITION,
    name: str = "Offers",
) -> dict[str, Any]:
    """Stream that rotates the campaign's offers."""
    return {
        "campaign_id": campaign_id,
        "name": name,
        "type": STREAM_TYPE_REGULAR,
        "schema": SCHEMA_LANDINGS,
        # Keitaro validates ``action_type`` on every stream, even when the
        # schema rotates offers and performs no action of its own.
        "action_type": ACTION_HTTP_REDIRECT,
        "action_payload": "",
        "position": position,
        "weight": TOTAL_SHARE,
        "state": STATE_ACTIVE,
        "collect_clicks": True,
        "offers": build_stream_offers(offer_ids),
    }


def build_stream_offers(offer_ids: list[int]) -> list[dict[str, Any]]:
    """Turn offer ids into stream offer slots with evenly distributed shares."""
    shares = distribute_shares(len(offer_ids))
    return [
        {"offer_id": offer_id, "share": share, "state": STATE_ACTIVE}
        for offer_id, share in zip(offer_ids, shares, strict=True)
    ]


def distribute_with_pins(pins: list[int | None], total: int = TOTAL_SHARE) -> list[int]:
    """Spread ``total`` over slots, leaving pinned shares untouched.

    ``pins`` holds the pinned share for each slot, or ``None`` when the slot
    floats. Pinned values are kept verbatim and the remainder is split evenly
    between the floating slots, so the result always sums to ``total``.

    ``distribute_with_pins([25, None, None]) -> [25, 38, 37]``
    """
    pinned_total = sum(pin for pin in pins if pin is not None)
    if pinned_total > total:
        msg = f"Pinned shares add up to {pinned_total}%, which exceeds {total}%"
        raise ValueError(msg)

    floating = [index for index, pin in enumerate(pins) if pin is None]
    shares = distribute_shares(len(floating), total - pinned_total)

    result: list[int] = [pin if pin is not None else 0 for pin in pins]
    for index, share in zip(floating, shares, strict=True):
        result[index] = share
    return result


def distribute_shares(count: int, total: int = TOTAL_SHARE) -> list[int]:
    """Split ``total`` into ``count`` integer shares that sum exactly to it.

    ``distribute_shares(3) -> [34, 33, 33]``
    """
    if count <= 0:
        return []
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def build_report_payload(
    *,
    campaign_ids: list[int],
    date_from: str,
    date_to: str,
    timezone: str = "UTC",
    grouping: str = "campaign_id",
) -> dict[str, Any]:
    """Payload for ``POST /admin_api/v1/report/build``."""
    return {
        "range": {"from": date_from, "to": date_to, "timezone": timezone},
        "columns": [],
        "metrics": [
            "clicks",
            "campaign_unique_clicks",
            "conversions",
            "leads",
            "sales",
            "rejected",
            "revenue",
            "cost",
            "profit",
            "roi",
            "cr",
            "epc",
        ],
        "grouping": [grouping],
        "filters": [
            {
                "name": "campaign_id",
                "operator": "IN_LIST",
                "expression": [str(campaign_id) for campaign_id in campaign_ids],
            }
        ],
        "sort": [{"name": "clicks", "order": "desc"}],
        "limit": 500,
        "offset": 0,
    }
