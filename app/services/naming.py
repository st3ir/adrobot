"""Campaign name normalisation and validation."""

from __future__ import annotations

import re

MAX_CAMPAIGN_NAME_LENGTH = 255
#: Letters (any alphabet), digits, spaces and a few separators.
_ALLOWED_NAME = re.compile(r"^[\w\s().\-]+$", re.UNICODE)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class InvalidCampaignNameError(ValueError):
    """Raised when a campaign name cannot be used."""


def normalize_campaign_name(raw_name: str, *, prefix: str) -> str:
    """Trim, validate and prefix a campaign name.

    The team convention is that every test campaign is named
    ``test_<surname>_<something>``; the prefix is added when missing so the
    rule cannot be forgotten, and never doubled when already present.
    """
    # Collapse any whitespace (including newlines/tabs) to single spaces first,
    # then drop the remaining control characters entirely.
    name = re.sub(r"\s+", " ", raw_name).strip()
    name = _CONTROL_CHARS.sub("", name).strip()

    if not name:
        msg = "Campaign name must not be empty."
        raise InvalidCampaignNameError(msg)
    if not _ALLOWED_NAME.match(name):
        msg = "Campaign name may only contain letters, digits, spaces, '.', '-', '_' and '()'."
        raise InvalidCampaignNameError(msg)

    full_name = name if name.lower().startswith(prefix.lower()) else f"{prefix}{name}"
    if len(full_name) > MAX_CAMPAIGN_NAME_LENGTH:
        msg = f"Campaign name must be at most {MAX_CAMPAIGN_NAME_LENGTH} characters."
        raise InvalidCampaignNameError(msg)
    return full_name
