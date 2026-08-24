from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.services.tenant_identity import TenantLoginRuntimeSettings
from inventory_control.identity import TenantBrowserSessionPolicy
from inventory_control.sms import (
    SmsDeliveryOutcome,
    SmsPolicy,
    SmsProviderRequest,
    SmsPurpose,
    TencentCloudSmsProvider,
    TencentCloudSmsSettings,
    TrustedSourceBucket,
)


def _settings(**overrides):
    values = {
        "sms_sdk_app_id": "1400006666",
        "sign_name": "已审核平台签名",
        "template_id": "449739",
        "region": "ap-guangzhou",
        "request_timeout_seconds": 10,
        "template_parameter_order": ("code", "ttl_minutes"),
        "verification_ttl_minutes": 5,
    }
    values.update(overrides)
    return TencentCloudSmsSettings(**values)


class _SdkRequest:
    pass


class _Client:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def SendSms(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def _provider(*, response=None, error=None, settings=None):
    client = _Client(response=response, error=error)
    provider = TencentCloudSmsProvider(
        settings=settings or _settings(),
        client=client,
        request_factory=_SdkRequest,
    )
    return provider, client


def _request():
    return SmsProviderRequest(
        challenge_id="10000000-0000-4000-8000-000000000001",
        canonical_phone_e164="+8613800138001",
        purpose=SmsPurpose.LOGIN,
        plaintext_code="123456",
    )


def test_official_request_fields_and_success_mapping_are_exact() -> None:
    provider, client = _provider(
        response=SimpleNamespace(
            SendStatusSet=[SimpleNamespace(Code="Ok")]
        )
    )
    request = _request()

    result = provider.send_verification(request)

    assert result is SmsDeliveryOutcome.SENT
    sent = client.requests[0]
    assert sent.SmsSdkAppId == "1400006666"
    assert sent.SignName == "已审核平台签名"
    assert sent.TemplateId == "449739"
    assert sent.TemplateParamSet == ["123456", "5"]
    assert sent.PhoneNumberSet == ["+8613800138001"]
    assert sent.SessionContext == sent.ExtendCode == sent.SenderId == ""
    with pytest.raises(RuntimeError):
        request.take_plaintext_code()


def test_explicit_provider_rejection_is_failed_without_error_echo() -> None:
    provider, _client = _provider(
        response=SimpleNamespace(
            SendStatusSet=[
                SimpleNamespace(Code="FailedOperation.TemplateUnapproved")
            ]
        )
    )

    assert provider.send_verification(_request()) is SmsDeliveryOutcome.FAILED


@pytest.mark.parametrize(
    "response",
    [
        object(),
        SimpleNamespace(SendStatusSet=[]),
        SimpleNamespace(SendStatusSet=[SimpleNamespace(Code=None)]),
    ],
)
def test_ambiguous_response_is_send_unknown(response) -> None:
    provider, _client = _provider(response=response)

    assert provider.send_verification(
        _request()
    ) is SmsDeliveryOutcome.SEND_UNKNOWN


def test_transport_exception_is_left_for_runtime_to_record_unknown() -> None:
    provider, _client = _provider(error=TimeoutError("provider timeout"))

    with pytest.raises(TimeoutError, match="provider timeout"):
        provider.send_verification(_request())


def test_template_parameter_order_is_explicit_and_policy_bound() -> None:
    provider, client = _provider(
        settings=_settings(
            template_parameter_order=("ttl_minutes", "code")
        ),
        response=SimpleNamespace(
            SendStatusSet=[SimpleNamespace(Code="Ok")]
        ),
    )
    provider.validate_sms_policy(SmsPolicy(challenge_ttl_seconds=300))

    provider.send_verification(_request())

    assert client.requests[0].TemplateParamSet == ["5", "123456"]
    with pytest.raises(ValueError, match="TTL"):
        provider.validate_sms_policy(SmsPolicy(challenge_ttl_seconds=240))


def test_login_runtime_settings_validate_provider_policy_without_secrets() -> None:
    provider, _client = _provider(response=None)

    configured = TenantLoginRuntimeSettings(
        sms_provider=provider,
        sms_policy=SmsPolicy(),
        session_policy=TenantBrowserSessionPolicy(
            version=1,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
        ),
        trusted_source_resolver=lambda _request: (
            TrustedSourceBucket.unknown()
        ),
    )

    assert "1400006666" not in repr(configured)
    assert "449739" not in repr(configured)
    assert "已审核平台签名" not in repr(provider)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sms_sdk_app_id": "not-digits"},
        {"template_id": ""},
        {"region": ""},
        {"request_timeout_seconds": 31},
        {"template_parameter_order": ("ttl_minutes",)},
        {"template_parameter_order": ("code", "code")},
        {"verification_ttl_minutes": 6},
    ],
)
def test_settings_fail_closed_without_defaults(overrides) -> None:
    with pytest.raises(ValueError):
        _settings(**overrides)
