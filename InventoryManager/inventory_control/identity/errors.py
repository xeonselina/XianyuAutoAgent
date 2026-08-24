"""Fixed public errors for control-plane identity primitives."""

from __future__ import annotations


class PhoneNormalizationError(ValueError):
    """A client-safe phone-format failure that never echoes the input."""

    code = "PHONE_IDENTITY_INVALID"
    public_message = "Core supports valid mainland-China mobile numbers only."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class InvalidOpaqueTokenError(ValueError):
    """A client-safe malformed-token failure with no account information."""

    code = "IDENTITY_CREDENTIAL_INVALID"
    public_message = "The identity credential is invalid."

    def __init__(self) -> None:
        super().__init__(self.public_message)
