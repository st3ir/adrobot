"""Country reference data."""

from __future__ import annotations

import pytest
from app.core.geo import COUNTRIES, country_name, normalize_country_code


class TestCountryTable:
    def test_contains_the_usual_suspects(self) -> None:
        for code in ("AU", "MX", "RO", "US", "DE", "RU"):
            assert code in COUNTRIES

    def test_codes_are_two_uppercase_letters(self) -> None:
        assert all(len(code) == 2 and code.isupper() for code in COUNTRIES)

    def test_is_reasonably_complete(self) -> None:
        assert len(COUNTRIES) > 240


class TestNormalizeCountryCode:
    @pytest.mark.parametrize(("value", "expected"), [("au", "AU"), (" mx ", "MX"), ("RO", "RO")])
    def test_normalises_known_codes(self, value: str, expected: str) -> None:
        assert normalize_country_code(value) == expected

    @pytest.mark.parametrize("value", ["", "XX", "AUS", "1", "../etc"])
    def test_rejects_unknown_codes(self, value: str) -> None:
        assert normalize_country_code(value) is None

    def test_country_name_falls_back_to_the_code(self) -> None:
        assert country_name("au") == "Australia"
        assert country_name("zz") == "ZZ"
