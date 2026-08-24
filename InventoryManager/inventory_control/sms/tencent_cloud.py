"""Tencent Cloud SMS API v20210111 adapter with no embedded credentials."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from .contracts import (
    SmsDeliveryOutcome,
    SmsPolicy,
    SmsProviderRequest,
)


_DIGITS = re.compile(r"[0-9]{5,32}", re.ASCII)
_REGION = re.compile(r"[a-z][a-z0-9-]{1,31}", re.ASCII)
_TEMPLATE_PARAMETER_NAMES = frozenset({"code", "ttl_minutes"})


class TencentCloudSmsConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class TencentCloudSmsSettings:
    """Non-secret, deployment-owned approved SMS application settings."""

    sms_sdk_app_id: str
    sign_name: str
    template_id: str
    region: str
    request_timeout_seconds: int
    template_parameter_order: tuple[str, ...]
    verification_ttl_minutes: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sms_sdk_app_id, str)
            or _DIGITS.fullmatch(self.sms_sdk_app_id) is None
            or not isinstance(self.template_id, str)
            or _DIGITS.fullmatch(self.template_id) is None
            or not isinstance(self.region, str)
            or _REGION.fullmatch(self.region) is None
            or not isinstance(self.sign_name, str)
            or self.sign_name != self.sign_name.strip()
            or not 1 <= len(self.sign_name) <= 64
            or any(ord(character) < 32 for character in self.sign_name)
            or isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, int)
            or not 1 <= self.request_timeout_seconds <= 30
            or not isinstance(self.template_parameter_order, tuple)
            or not self.template_parameter_order
            or len(set(self.template_parameter_order))
            != len(self.template_parameter_order)
            or not set(self.template_parameter_order).issubset(
                _TEMPLATE_PARAMETER_NAMES
            )
            or "code" not in self.template_parameter_order
            or isinstance(self.verification_ttl_minutes, bool)
            or not isinstance(self.verification_ttl_minutes, int)
            or not 1 <= self.verification_ttl_minutes <= 5
        ):
            raise ValueError("Tencent Cloud SMS settings are invalid")

    def __repr__(self) -> str:
        return (
            "TencentCloudSmsSettings("
            f"region={self.region!r}, "
            f"request_timeout_seconds={self.request_timeout_seconds}, "
            f"template_parameter_order={self.template_parameter_order!r}, "
            "<application-metadata-redacted>)"
        )


class TencentCloudSmsProvider:
    """Submit one verification SMS through an injected official SDK client."""

    __slots__ = ("_settings", "_client", "_request_factory")

    def __init__(
        self,
        *,
        settings: TencentCloudSmsSettings,
        client: object,
        request_factory: Callable[[], object],
    ) -> None:
        if not isinstance(settings, TencentCloudSmsSettings):
            raise TypeError("settings must be TencentCloudSmsSettings")
        if not callable(getattr(client, "SendSms", None)):
            raise TypeError("client must provide SendSms")
        if not callable(request_factory):
            raise TypeError("request_factory must be callable")
        self._settings = settings
        self._client = client
        self._request_factory = request_factory

    def validate_sms_policy(self, policy: SmsPolicy) -> None:
        if not isinstance(policy, SmsPolicy):
            raise TypeError("policy must be an SmsPolicy")
        if (
            "ttl_minutes" in self._settings.template_parameter_order
            and policy.challenge_ttl_seconds
            != self._settings.verification_ttl_minutes * 60
        ):
            raise ValueError(
                "SMS template TTL must match the challenge policy"
            )

    def send_verification(
        self,
        request: SmsProviderRequest,
    ) -> SmsDeliveryOutcome:
        if not isinstance(request, SmsProviderRequest):
            raise TypeError("request must be an SmsProviderRequest")
        code = request.take_plaintext_code()
        sdk_request = self._request_factory()
        parameters = {
            "code": code,
            "ttl_minutes": str(self._settings.verification_ttl_minutes),
        }
        sdk_request.SmsSdkAppId = self._settings.sms_sdk_app_id
        sdk_request.SignName = self._settings.sign_name
        sdk_request.TemplateId = self._settings.template_id
        sdk_request.TemplateParamSet = [
            parameters[name]
            for name in self._settings.template_parameter_order
        ]
        sdk_request.PhoneNumberSet = [request.canonical_phone_e164]
        sdk_request.SessionContext = ""
        sdk_request.ExtendCode = ""
        sdk_request.SenderId = ""

        response = self._client.SendSms(sdk_request)
        statuses = getattr(response, "SendStatusSet", None)
        if not isinstance(statuses, (list, tuple)) or len(statuses) != 1:
            return SmsDeliveryOutcome.SEND_UNKNOWN
        status_code = getattr(statuses[0], "Code", None)
        if status_code == "Ok":
            return SmsDeliveryOutcome.SENT
        if isinstance(status_code, str) and status_code:
            return SmsDeliveryOutcome.FAILED
        return SmsDeliveryOutcome.SEND_UNKNOWN

    def __repr__(self) -> str:
        return "TencentCloudSmsProvider(api_version='2021-01-11', <redacted>)"


def build_tencent_cloud_sms_provider(
    *,
    secret_id: str,
    secret_key: str,
    settings: TencentCloudSmsSettings,
) -> TencentCloudSmsProvider:
    """Build the official synchronous SDK client without sending a request."""

    if (
        not isinstance(secret_id, str)
        or not secret_id
        or not isinstance(secret_key, str)
        or not secret_key
        or not isinstance(settings, TencentCloudSmsSettings)
    ):
        raise TencentCloudSmsConfigurationError(
            "Tencent Cloud SMS credentials/settings are unavailable"
        )
    try:
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.sms.v20210111 import models, sms_client
    except ImportError:
        raise TencentCloudSmsConfigurationError(
            "Tencent Cloud SMS SDK is unavailable"
        ) from None

    http_profile = HttpProfile()
    http_profile.reqMethod = "POST"
    http_profile.reqTimeout = settings.request_timeout_seconds
    http_profile.endpoint = "sms.tencentcloudapi.com"
    client_profile = ClientProfile()
    client_profile.signMethod = "TC3-HMAC-SHA256"
    client_profile.language = "en-US"
    client_profile.httpProfile = http_profile
    credentials = credential.Credential(secret_id, secret_key)
    client = sms_client.SmsClient(
        credentials,
        settings.region,
        client_profile,
    )
    return TencentCloudSmsProvider(
        settings=settings,
        client=client,
        request_factory=models.SendSmsRequest,
    )


__all__ = [
    "TencentCloudSmsConfigurationError",
    "TencentCloudSmsProvider",
    "TencentCloudSmsSettings",
    "build_tencent_cloud_sms_provider",
]
