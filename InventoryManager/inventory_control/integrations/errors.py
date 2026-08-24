"""Stable, non-secret errors for tenant integration state changes."""

from __future__ import annotations


class TenantIntegrationError(RuntimeError):
    """Base error whose text is safe for logs and API error mapping."""

    code = "TENANT_INTEGRATION_ERROR"
    public_message = "tenant integration operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class IntegrationTransactionRequiredError(TenantIntegrationError):
    code = "INTEGRATION_TRANSACTION_REQUIRED"
    public_message = "an explicit caller-owned transaction is required"


class IntegrationInputError(TenantIntegrationError):
    code = "INTEGRATION_INPUT_INVALID"
    public_message = "tenant integration input is invalid"


class IntegrationNotFoundError(TenantIntegrationError):
    code = "INTEGRATION_NOT_FOUND"
    public_message = "tenant integration resource was not found"


class IntegrationIdempotencyConflictError(TenantIntegrationError):
    code = "INTEGRATION_IDEMPOTENCY_CONFLICT"
    public_message = "tenant integration idempotency key conflicts"


class IntegrationStateConflictError(TenantIntegrationError):
    code = "INTEGRATION_STATE_CONFLICT"
    public_message = "tenant integration state changed"


class IntegrationValidationUnknownError(TenantIntegrationError):
    code = "INTEGRATION_VALIDATION_UNKNOWN"
    public_message = "provider validation requires explicit reconciliation"


class IntegrationCredentialUnavailableError(TenantIntegrationError):
    code = "INTEGRATION_CREDENTIAL_UNAVAILABLE"
    public_message = "the exact credential revision is unavailable"


class IntegrationCredentialAuthenticationError(TenantIntegrationError):
    code = "INTEGRATION_CREDENTIAL_AUTHENTICATION_FAILED"
    public_message = "the exact credential revision could not be authenticated"


class IntegrationPersistenceError(TenantIntegrationError):
    code = "INTEGRATION_PERSISTENCE_FAILED"
    public_message = "tenant integration state could not be persisted"
