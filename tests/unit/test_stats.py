"""Statistics normalisation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.services.stats import DateRange, Metrics, StatsService

from tests.fakes import FakeKeitaro


class TestDateRange:
    def test_last_day_is_today(self) -> None:
        period = DateRange.last_days(1)
        today = datetime.now(UTC).date()
        assert period.date_from == today
        assert period.date_to == today

    def test_inclusive_window(self) -> None:
        period = DateRange.last_days(7)
        assert (period.date_to - period.date_from).days == 6

    @pytest.mark.parametrize(("days", "expected"), [(0, 0), (-5, 0), (100_000, 364)])
    def test_clamps_out_of_range_values(self, days: int, expected: int) -> None:
        period = DateRange.last_days(days)
        assert (period.date_to - period.date_from).days == expected


class TestMetrics:
    def test_reads_the_unique_clicks_alias(self) -> None:
        assert Metrics.from_row({"campaign_unique_clicks": 42}).unique_clicks == 42
        assert Metrics.from_row({"unique_clicks": 7}).unique_clicks == 7

    def test_missing_metrics_default_to_zero(self) -> None:
        assert Metrics.from_row({}) == Metrics()

    def test_tolerates_strings_and_nulls(self) -> None:
        metrics = Metrics.from_row({"clicks": "15", "revenue": "10.5", "cost": None})
        assert metrics.clicks == 15
        assert metrics.revenue == 10.5
        assert metrics.cost == 0.0

    def test_tolerates_garbage(self) -> None:
        assert Metrics.from_row({"clicks": "n/a", "roi": {}}).clicks == 0


class TestStatsService:
    async def test_splits_totals_and_per_offer_rows(self) -> None:
        keitaro = FakeKeitaro()
        keitaro.report_rows["campaign_id"] = [{"clicks": 200, "conversions": 10}]
        keitaro.report_rows["offer_id"] = [
            {"offer_id": 1, "clicks": 120},
            {"offer_id": 2, "clicks": 80},
        ]
        stats = await StatsService(keitaro).campaign_stats(1, DateRange.last_days(30))
        assert stats.totals.clicks == 200
        assert stats.per_offer[1].clicks == 120
        assert stats.per_offer[2].clicks == 80

    async def test_rows_without_an_offer_id_are_skipped(self) -> None:
        keitaro = FakeKeitaro()
        keitaro.report_rows["offer_id"] = [{"clicks": 5}, {"offer_id": 0, "clicks": 5}]
        stats = await StatsService(keitaro).campaign_stats(1, DateRange.last_days(30))
        assert stats.per_offer == {}

    async def test_upstream_failure_is_not_fatal(self) -> None:
        keitaro = FakeKeitaro()
        keitaro.report_fails = True
        stats = await StatsService(keitaro).campaign_stats(1, DateRange.last_days(30))
        assert stats.available is False
        assert stats.totals == Metrics()
