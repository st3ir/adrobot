"""Audit context sanitising."""

from __future__ import annotations

from app.services.audit import sanitize_context


class TestSanitizeContext:
    def test_empty_context_is_dropped(self) -> None:
        assert sanitize_context(None) is None
        assert sanitize_context({}) is None

    def test_removes_secret_looking_keys(self) -> None:
        context = {
            "offer_id": 1,
            "password": "hunter2",
            "api_key": "abc",
            "Authorization": "Bearer x",
            "session_token": "t",
            "cookie": "c",
        }
        assert sanitize_context(context) == {"offer_id": 1}

    def test_truncates_long_strings(self) -> None:
        cleaned = sanitize_context({"name": "x" * 5000})
        assert cleaned is not None
        assert len(cleaned["name"]) == 500

    def test_clamps_long_lists(self) -> None:
        cleaned = sanitize_context({"ids": list(range(500))})
        assert cleaned is not None
        assert len(cleaned["ids"]) == 50

    def test_keeps_scalars(self) -> None:
        assert sanitize_context({"a": 1, "b": 1.5, "c": True, "d": None}) == {
            "a": 1,
            "b": 1.5,
            "c": True,
            "d": None,
        }

    def test_stringifies_unknown_types(self) -> None:
        cleaned = sanitize_context({"obj": {"nested": 1}})
        assert cleaned is not None
        assert isinstance(cleaned["obj"], str)
