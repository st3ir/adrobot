"""Secret redaction in logs."""

from __future__ import annotations

import logging

from app.core.logging import REDACTED, SecretRedactingFilter


def make_record(message: str) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, (), None)


class TestSecretRedactingFilter:
    def test_removes_known_secrets(self) -> None:
        record = make_record("calling with key super-secret-key-value")
        SecretRedactingFilter(["super-secret-key-value"]).filter(record)
        assert "super-secret-key-value" not in record.msg
        assert REDACTED in record.msg

    def test_redacts_secret_looking_pairs(self) -> None:
        record = make_record('{"Api-Key": "abcdef123456", "offer_id": 7}')
        SecretRedactingFilter().filter(record)
        assert "abcdef123456" not in record.msg
        assert "offer_id" in record.msg

    def test_redacts_authorization_headers(self) -> None:
        record = make_record("Authorization: Bearer tok_123456789")
        SecretRedactingFilter().filter(record)
        assert "tok_123456789" not in record.msg

    def test_ignores_short_secrets(self) -> None:
        """Short values would redact unrelated text; they are skipped."""
        record = make_record("the offer id is 42")
        SecretRedactingFilter(["42"]).filter(record)
        assert "42" in record.msg
