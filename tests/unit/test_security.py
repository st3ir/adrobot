"""Password hashing, session tokens and CSRF helpers."""

from __future__ import annotations

from app.core.security import (
    SessionPayload,
    SessionTokenCodec,
    generate_csrf_token,
    hash_password,
    tokens_match,
    verify_password,
)

SECRET = "s" * 48


class TestPasswordHashing:
    def test_hash_is_salted_and_verifiable(self) -> None:
        first = hash_password("correct horse")
        second = hash_password("correct horse")
        assert first != second
        assert verify_password("correct horse", first)
        assert verify_password("correct horse", second)

    def test_rejects_a_wrong_password(self) -> None:
        assert not verify_password("nope", hash_password("correct horse"))

    def test_uses_argon2id(self) -> None:
        assert hash_password("x").startswith("$argon2id$")

    def test_malformed_hash_is_not_a_crash(self) -> None:
        assert not verify_password("x", "not-a-hash")


class TestSessionTokenCodec:
    def test_round_trip(self) -> None:
        codec = SessionTokenCodec(SECRET, max_age_seconds=60)
        token = codec.encode(SessionPayload(user_id=7, csrf_token="abc"))
        payload = codec.decode(token)
        assert payload == SessionPayload(user_id=7, csrf_token="abc")

    def test_rejects_a_token_signed_with_another_secret(self) -> None:
        token = SessionTokenCodec("other" * 10, max_age_seconds=60).encode(
            SessionPayload(user_id=7, csrf_token="abc")
        )
        assert SessionTokenCodec(SECRET, max_age_seconds=60).decode(token) is None

    def test_rejects_a_tampered_token(self) -> None:
        codec = SessionTokenCodec(SECRET, max_age_seconds=60)
        token = codec.encode(SessionPayload(user_id=7, csrf_token="abc"))
        assert codec.decode(token[:-3] + "zzz") is None

    def test_rejects_an_expired_token(self, monkeypatch) -> None:
        import time
        from types import SimpleNamespace

        import itsdangerous.timed

        codec = SessionTokenCodec(SECRET, max_age_seconds=60)
        token = codec.encode(SessionPayload(user_id=7, csrf_token="abc"))
        # Travel two minutes into the future instead of sleeping.
        monkeypatch.setattr(
            itsdangerous.timed, "time", SimpleNamespace(time=lambda: time.time() + 120)
        )
        assert codec.decode(token) is None

    def test_rejects_garbage(self) -> None:
        assert SessionTokenCodec(SECRET, max_age_seconds=60).decode("garbage") is None


class TestCsrfTokens:
    def test_tokens_are_unique_and_long(self) -> None:
        tokens = {generate_csrf_token() for _ in range(50)}
        assert len(tokens) == 50
        assert all(len(token) >= 32 for token in tokens)

    def test_comparison(self) -> None:
        assert tokens_match("abc", "abc")
        assert not tokens_match("abc", "abd")
        assert not tokens_match("abc", "")
