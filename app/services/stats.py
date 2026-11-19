"""Campaign and offer statistics, built on Keitaro's report builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.exceptions import KeitaroError
from app.core.logging import get_logger
from app.keitaro import builders
from app.keitaro.protocols import ReportReader

logger = get_logger(__name__)

DEFAULT_LOOKBACK_DAYS = 30
MAX_LOOKBACK_DAYS = 365

_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "clicks": ("clicks",),
    "unique_clicks": ("campaign_unique_clicks", "unique_clicks"),
    "conversions": ("conversions",),
    "leads": ("leads",),
    "sales": ("sales",),
    "rejected": ("rejected",),
    "revenue": ("revenue",),
    "cost": ("cost",),
    "profit": ("profit",),
    "roi": ("roi",),
    "cr": ("cr",),
    "epc": ("epc",),
}


@dataclass(frozen=True, slots=True)
class DateRange:
    """An inclusive reporting period."""

    date_from: date
    date_to: date

    @classmethod
    def last_days(cls, days: int = DEFAULT_LOOKBACK_DAYS) -> DateRange:
        bounded = max(1, min(days, MAX_LOOKBACK_DAYS))
        today = datetime.now(UTC).date()
        return cls(date_from=today - timedelta(days=bounded - 1), date_to=today)

    def as_payload(self) -> tuple[str, str]:
        return self.date_from.isoformat(), self.date_to.isoformat()


@dataclass(frozen=True, slots=True)
class Metrics:
    """A normalized metric row. Missing upstream metrics default to zero."""

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

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Metrics:
        def pick(field_name: str) -> Any:
            for alias in _METRIC_ALIASES[field_name]:
                if alias in row and row[alias] is not None:
                    return row[alias]
            return 0

        return cls(
            clicks=_to_int(pick("clicks")),
            unique_clicks=_to_int(pick("unique_clicks")),
            conversions=_to_int(pick("conversions")),
            leads=_to_int(pick("leads")),
            sales=_to_int(pick("sales")),
            rejected=_to_int(pick("rejected")),
            revenue=_to_float(pick("revenue")),
            cost=_to_float(pick("cost")),
            profit=_to_float(pick("profit")),
            roi=_to_float(pick("roi")),
            cr=_to_float(pick("cr")),
            epc=_to_float(pick("epc")),
        )


@dataclass(frozen=True, slots=True)
class CampaignStats:
    """Campaign totals plus a per-offer breakdown."""

    totals: Metrics = field(default_factory=Metrics)
    per_offer: dict[int, Metrics] = field(default_factory=dict)
    available: bool = True


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


class StatsService:
    """Fetches report rows and normalizes them into :class:`Metrics`."""

    def __init__(self, reports: ReportReader, *, timezone: str = "UTC") -> None:
        self._reports = reports
        self._timezone = timezone

    async def campaign_stats(self, campaign_id: int, period: DateRange) -> CampaignStats:
        """Totals for the campaign and a breakdown per offer.

        Statistics are informational: when Keitaro's report builder is not
        available the editor must still work, so failures degrade to empty
        metrics instead of propagating.
        """
        date_from, date_to = period.as_payload()
        try:
            totals = await self._fetch(campaign_id, date_from, date_to, grouping="campaign_id")
            per_offer_rows = await self._fetch(
                campaign_id, date_from, date_to, grouping="offer_id"
            )
        except KeitaroError as exc:
            logger.warning("Statistics unavailable for campaign %s: %s", campaign_id, exc.code)
            return CampaignStats(available=False)

        campaign_totals = Metrics.from_row(totals[0]) if totals else Metrics()
        per_offer: dict[int, Metrics] = {}
        for row in per_offer_rows:
            offer_id = _to_int(row.get("offer_id"))
            if offer_id:
                per_offer[offer_id] = Metrics.from_row(row)
        return CampaignStats(totals=campaign_totals, per_offer=per_offer)

    async def _fetch(
        self, campaign_id: int, date_from: str, date_to: str, *, grouping: str
    ) -> list[dict[str, Any]]:
        payload = builders.build_report_payload(
            campaign_ids=[campaign_id],
            date_from=date_from,
            date_to=date_to,
            timezone=self._timezone,
            grouping=grouping,
        )
        body = await self._reports.build_report(payload)
        rows = body.get("rows")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
