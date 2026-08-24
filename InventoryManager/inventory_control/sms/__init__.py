"""Purpose-bound SMS challenge service and safe adapter contracts."""

from .contracts import (
    CanonicalActionPayload,
    CanonicalSmsPhone,
    PreparedSmsDelivery,
    SmsChallengeContext,
    SmsDeliveryOutcome,
    SmsPolicy,
    SmsProvider,
    SmsProviderRequest,
    SmsPurpose,
    SmsVerificationResult,
    TrustedSourceBucket,
)
from .crypto import SMS_HMAC_PROTOCOL_VERSION, calculate_code_hmac, verify_code_hmac
from .service import (
    SmsChallengeService,
    SmsDeliveryStateError,
    SmsSendRejected,
)
from .trusted_proxy import (
    TrustedProxySourcePolicy,
    TrustedProxySourceResolver,
)
from .tencent_cloud import (
    TencentCloudSmsConfigurationError,
    TencentCloudSmsProvider,
    TencentCloudSmsSettings,
    build_tencent_cloud_sms_provider,
)

__all__ = [
    "CanonicalActionPayload",
    "CanonicalSmsPhone",
    "PreparedSmsDelivery",
    "SmsChallengeContext",
    "SmsChallengeService",
    "SmsDeliveryStateError",
    "SmsDeliveryOutcome",
    "SmsPolicy",
    "SmsProvider",
    "SmsProviderRequest",
    "SmsPurpose",
    "SmsSendRejected",
    "SmsVerificationResult",
    "TrustedSourceBucket",
    "TrustedProxySourcePolicy",
    "TrustedProxySourceResolver",
    "TencentCloudSmsConfigurationError",
    "TencentCloudSmsProvider",
    "TencentCloudSmsSettings",
    "build_tencent_cloud_sms_provider",
    "SMS_HMAC_PROTOCOL_VERSION",
    "calculate_code_hmac",
    "verify_code_hmac",
]
