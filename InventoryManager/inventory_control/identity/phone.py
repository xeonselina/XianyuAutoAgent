"""Versioned normalization for tenant identity phone numbers only."""

from __future__ import annotations

import re

from .errors import PhoneNormalizationError


PHONE_NORMALIZATION_VERSION = 1
CN_MOBILE_METADATA_VERSION = "cn-mobile-v1-2026-07"

# Frozen version-one CN mobile metadata.  Keeping this rule in the identity
# boundary, with an explicit metadata version, prevents registration, login,
# invitation, and challenge flows from growing independent prefix rules.
_CN_MOBILE_NATIONAL_PATTERN = re.compile(
    r"(?:"
    r"1(?:610[0-9]|740[0-5])[0-9]{6}"
    r"|"
    r"1(?:[38][0-9]|4[57]|[59][0-35-9]|6[25-7]|7[0-35-8])[0-9]{8}"
    r")",
    flags=re.ASCII,
)
_ALLOWED_INPUT_PATTERN = re.compile(r"[+0-9 -]+", flags=re.ASCII)


class PhoneIdentityNormalizer:
    """Normalize supported tenant identities to one ASCII E.164 value.

    This validator is intentionally narrower than a business-contact phone
    validator.  It accepts only a national mainland-China mobile number or an
    explicit ``+86`` equivalent.  ASCII space and ``-`` are the only removable
    display separators.
    """

    normalization_version = PHONE_NORMALIZATION_VERSION
    metadata_version = CN_MOBILE_METADATA_VERSION

    def normalize(self, raw_phone: str) -> str:
        if not isinstance(raw_phone, str) or not _ALLOWED_INPUT_PATTERN.fullmatch(
            raw_phone
        ):
            raise PhoneNormalizationError()

        compact = raw_phone.replace(" ", "").replace("-", "")
        if compact.startswith("+86"):
            national_number = compact[3:]
        elif compact.startswith("+"):
            raise PhoneNormalizationError()
        else:
            national_number = compact

        if not _CN_MOBILE_NATIONAL_PATTERN.fullmatch(national_number):
            raise PhoneNormalizationError()

        return "+86" + national_number


_DEFAULT_NORMALIZER = PhoneIdentityNormalizer()


def normalize_tenant_phone(raw_phone: str) -> str:
    """Return the canonical ``+86`` tenant identity phone number."""

    return _DEFAULT_NORMALIZER.normalize(raw_phone)
