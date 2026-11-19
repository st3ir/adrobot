"""Campaign name normalisation."""

from __future__ import annotations

import pytest
from app.services.naming import InvalidCampaignNameError, normalize_campaign_name

PREFIX = "test_ivanov_"


class TestNormalizeCampaignName:
    def test_adds_the_team_prefix(self) -> None:
        assert normalize_campaign_name("campaign1", prefix=PREFIX) == "test_ivanov_campaign1"

    def test_does_not_double_an_existing_prefix(self) -> None:
        assert (
            normalize_campaign_name("test_ivanov_campaign1", prefix=PREFIX)
            == "test_ivanov_campaign1"
        )

    def test_prefix_match_is_case_insensitive(self) -> None:
        assert (
            normalize_campaign_name("TEST_IVANOV_Camp", prefix=PREFIX) == "TEST_IVANOV_Camp"
        )

    def test_collapses_whitespace(self) -> None:
        assert normalize_campaign_name("  my   camp  ", prefix=PREFIX) == "test_ivanov_my camp"

    def test_strips_control_characters(self) -> None:
        assert normalize_campaign_name("ca\x00mp\x1f", prefix=PREFIX) == "test_ivanov_camp"

    def test_allows_cyrillic(self) -> None:
        assert normalize_campaign_name("кампания", prefix=PREFIX) == "test_ivanov_кампания"

    def test_newlines_become_spaces(self) -> None:
        assert normalize_campaign_name("a\nb", prefix=PREFIX) == "test_ivanov_a b"

    @pytest.mark.parametrize("name", ["", "   ", "\x00", "a<script>", "drop; --", "a/b", "a'b"])
    def test_rejects_unsafe_names(self, name: str) -> None:
        with pytest.raises(InvalidCampaignNameError):
            normalize_campaign_name(name, prefix=PREFIX)

    def test_rejects_overlong_names(self) -> None:
        with pytest.raises(InvalidCampaignNameError):
            normalize_campaign_name("a" * 300, prefix=PREFIX)
