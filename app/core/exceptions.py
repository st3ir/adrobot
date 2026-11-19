"""Domain-level exception hierarchy.

Every error raised by the service layer is a subclass of :class:`AdrobotError`
and carries an HTTP status plus a *safe* message: one that can be shown to an
end user without leaking internals, upstream payloads or credentials.
"""

from __future__ import annotations

from http import HTTPStatus


class AdrobotError(Exception):
    """Base class for all expected application errors."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    safe_message: str = "Unexpected error."

    def __init__(self, safe_message: str | None = None, *, detail: str | None = None) -> None:
        self.safe_message = safe_message or type(self).safe_message
        # ``detail`` is for server-side logs only and is never serialized.
        self.detail = detail
        super().__init__(self.safe_message)


# --------------------------------------------------------------------------
# Authentication / authorization
# --------------------------------------------------------------------------
class AuthenticationError(AdrobotError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"
    safe_message = "Authentication required."


class InvalidCredentialsError(AuthenticationError):
    code = "invalid_credentials"
    safe_message = "Invalid email or password."


class CsrfError(AdrobotError):
    status_code = HTTPStatus.FORBIDDEN
    code = "csrf_failed"
    safe_message = "CSRF validation failed. Reload the page and try again."


class RateLimitedError(AdrobotError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"
    safe_message = "Too many requests. Please slow down."

    def __init__(self, retry_after: int = 60, **kwargs: str | None) -> None:
        super().__init__(**kwargs)
        self.retry_after = retry_after


# --------------------------------------------------------------------------
# Upstream (Keitaro) failures
# --------------------------------------------------------------------------
class KeitaroError(AdrobotError):
    status_code = HTTPStatus.BAD_GATEWAY
    code = "keitaro_error"
    safe_message = "Keitaro request failed."


class KeitaroAuthError(KeitaroError):
    code = "keitaro_unauthorized"
    safe_message = "Keitaro rejected the API key. Check KEITARO_API_KEY."


class KeitaroNotFoundError(KeitaroError):
    status_code = HTTPStatus.NOT_FOUND
    code = "keitaro_not_found"
    safe_message = "The requested Keitaro object does not exist."


class KeitaroValidationError(KeitaroError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "keitaro_validation_error"
    safe_message = "Keitaro rejected the request payload."


class KeitaroUnavailableError(KeitaroError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "keitaro_unavailable"
    safe_message = "Keitaro is unreachable. Try again in a moment."


# --------------------------------------------------------------------------
# Business rules
# --------------------------------------------------------------------------
class BusinessRuleError(AdrobotError):
    status_code = HTTPStatus.CONFLICT
    code = "business_rule_violation"
    safe_message = "Operation is not allowed in the current state."


class OfferAlreadyAttachedError(BusinessRuleError):
    code = "offer_already_attached"
    safe_message = "This offer is already attached to the campaign."


class OfferNotAttachedError(BusinessRuleError):
    status_code = HTTPStatus.NOT_FOUND
    code = "offer_not_attached"
    safe_message = "This offer is not attached to the campaign."


class NoOfferStreamError(BusinessRuleError):
    code = "no_offer_stream"
    safe_message = "The campaign has no stream that can hold offers."


class PinnedSharesExceededError(BusinessRuleError):
    code = "pinned_shares_exceeded"
    safe_message = "Pinned shares add up to more than 100%."


class NothingToPublishError(BusinessRuleError):
    code = "nothing_to_publish"
    safe_message = "There are no unpublished changes in this campaign."


class CampaignNotTrackedError(AdrobotError):
    status_code = HTTPStatus.NOT_FOUND
    code = "campaign_not_tracked"
    safe_message = "Fetch the campaign from Keitaro first."


class CatalogIncompleteError(AdrobotError):
    status_code = HTTPStatus.FAILED_DEPENDENCY
    code = "catalog_incomplete"
    safe_message = "Keitaro has no domain/group/source available for new campaigns."
