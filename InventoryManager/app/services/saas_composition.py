"""Atomic composition root for the migrated SaaS Core HTTP runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass

from flask import Flask

from app.services.gantt.http_runtime import (
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyGanttSaasHttpRuntime,
)
from app.services.inspection.http_runtime import (
    INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyInspectionSaasHttpRuntime,
)
from app.services.platform_identity.http_runtime import (
    PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION,
    PlatformLoginRuntimeSettings,
    SqlAlchemyPlatformIdentityHttpRuntime,
)
from app.services.platform_tenant_read.http_runtime import (
    PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyPlatformTenantReadHttpRuntime,
)
from app.services.platform_subscription_adjustment.http_runtime import (
    PLATFORM_SUBSCRIPTION_ADJUSTMENT_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyPlatformSubscriptionAdjustmentHttpRuntime,
)
from app.services.platform_redemption.http_runtime import (
    PLATFORM_REDEMPTION_HTTP_RUNTIME_EXTENSION,
    PlatformRedemptionRuntimeSettings,
    SqlAlchemyPlatformRedemptionHttpRuntime,
)
from app.services.rental.http_runtime import (
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyRentalSaasHttpRuntime,
)
from app.services.relay.http_runtime import (
    RELAY_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyRelaySaasHttpRuntime,
)
from app.services.shipping.tracking_http_runtime import (
    SF_TRACKING_HTTP_RUNTIME_EXTENSION,
    SqlAlchemySfTrackingHttpRuntime,
)
from app.services.shipping.batch_http_runtime import (
    SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION,
    SqlAlchemySfBatchShippingHttpRuntime,
)
from app.services.shipping.tracking_provider import SfTrackingProviderAdapter
from app.services.warehouse.http_runtime import (
    WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyWarehouseSaasHttpRuntime,
)
from app.services.xianyu_sync.http_runtime import (
    XIANYU_SYNC_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyXianyuSyncHttpRuntime,
)
from app.services.tenant_business.composition import (
    build_tenant_business_http_runtime,
)
from app.services.tenant_business.http_runtime import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantBusinessHttpRuntime,
)
from app.services.tenant_identity.http_runtime import (
    TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantIdentityHttpRuntime,
    TenantLoginRuntimeSettings,
)
from app.services.tenant_invitations.http_runtime import (
    TENANT_INVITATION_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantInvitationHttpRuntime,
)
from app.services.tenant_integrations.http_runtime import (
    TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantIntegrationHttpRuntime,
)
from app.services.tenant_integrations.provider_account_http_runtime import (
    TENANT_PROVIDER_ACCOUNT_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantProviderAccountHttpRuntime,
)
from app.services.tenant_subscription.http_runtime import (
    TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantSubscriptionHttpRuntime,
)
from inventory_control import ControlDatabase
from inventory_control.jobs import XianyuSyncJobCoordinator
from inventory_control.jobs.scheduler import TenantScheduleGate
from inventory_control.flask import EXTENSION_KEY as CONTROL_DATABASE_EXTENSION
from inventory_control.proofs import (
    GanttPreviewProofAdapter,
    SqlAlchemyGanttPreviewAuthorityReader,
)
from inventory_control.routing import (
    DatabaseInstanceRegistry,
    TenantEnginePoolSettings,
    SqlAlchemyTenantRouterScope,
)


SAAS_CORE_HTTP_RUNTIME_SETTINGS = "SAAS_CORE_HTTP_RUNTIME_SETTINGS"
ENABLE_SAAS_CORE_HTTP_RUNTIME = "ENABLE_SAAS_CORE_HTTP_RUNTIME"

_RUNTIME_EXTENSION_KEYS = (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
    INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION,
    WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION,
    RELAY_SAAS_HTTP_RUNTIME_EXTENSION,
    TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION,
    TENANT_INVITATION_HTTP_RUNTIME_EXTENSION,
    TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION,
    TENANT_PROVIDER_ACCOUNT_HTTP_RUNTIME_EXTENSION,
    TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION,
    PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION,
    PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION,
    PLATFORM_SUBSCRIPTION_ADJUSTMENT_HTTP_RUNTIME_EXTENSION,
    PLATFORM_REDEMPTION_HTTP_RUNTIME_EXTENSION,
    SF_TRACKING_HTTP_RUNTIME_EXTENSION,
    SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION,
    XIANYU_SYNC_HTTP_RUNTIME_EXTENSION,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SaasCoreHttpRuntimeSettings:
    """Deployment-owned structured settings; never a DSN or tenant route."""

    root_key_directory: str | os.PathLike[str]
    database_instances: DatabaseInstanceRegistry
    engine_pool_settings: TenantEnginePoolSettings
    max_cache_entries: int
    platform_read_policy_version: int
    platform_read_query_timeout_ms: int
    tenant_login: TenantLoginRuntimeSettings | None = None
    platform_login: PlatformLoginRuntimeSettings | None = None
    platform_redemption: PlatformRedemptionRuntimeSettings | None = None
    sf_tracking_adapter: SfTrackingProviderAdapter | None = None
    xianyu_schedule_gate: TenantScheduleGate | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.database_instances, DatabaseInstanceRegistry)
            or not isinstance(
                self.engine_pool_settings, TenantEnginePoolSettings
            )
            or isinstance(self.max_cache_entries, bool)
            or not isinstance(self.max_cache_entries, int)
            or self.max_cache_entries < 1
            or isinstance(self.platform_read_policy_version, bool)
            or not isinstance(self.platform_read_policy_version, int)
            or self.platform_read_policy_version < 1
            or isinstance(self.platform_read_query_timeout_ms, bool)
            or not isinstance(self.platform_read_query_timeout_ms, int)
            or not 100 <= self.platform_read_query_timeout_ms <= 10_000
            or (
                self.tenant_login is not None
                and not isinstance(
                    self.tenant_login, TenantLoginRuntimeSettings
                )
            )
            or (
                self.platform_login is not None
                and not isinstance(
                    self.platform_login, PlatformLoginRuntimeSettings
                )
            )
            or (
                self.platform_redemption is not None
                and not isinstance(
                    self.platform_redemption,
                    PlatformRedemptionRuntimeSettings,
                )
            )
            or (
                self.sf_tracking_adapter is not None
                and not callable(
                    getattr(self.sf_tracking_adapter, "query_routes", None)
                )
            )
            or (
                self.xianyu_schedule_gate is not None
                and not callable(
                    getattr(self.xianyu_schedule_gate, "evaluate", None)
                )
            )
        ):
            raise TypeError("SaaS Core HTTP runtime settings are invalid")
        try:
            root = os.fspath(self.root_key_directory)
        except TypeError:
            raise TypeError(
                "SaaS Core HTTP runtime settings are invalid"
            ) from None
        if not isinstance(root, str) or not os.path.isabs(root):
            raise ValueError("root key directory must be absolute")
        object.__setattr__(self, "root_key_directory", root)

    def __repr__(self) -> str:
        return (
            "SaasCoreHttpRuntimeSettings("
            "root_key_directory=<configured>, "
            f"database_instances={self.database_instances!r}, "
            f"engine_pool_settings={self.engine_pool_settings!r}, "
            f"max_cache_entries={self.max_cache_entries}, "
            f"sf_tracking_configured={self.sf_tracking_adapter is not None}, "
            f"xianyu_sync_configured={self.xianyu_schedule_gate is not None})"
        )


@dataclass(frozen=True, slots=True)
class SaasCoreHttpRuntimeBundle:
    tenant_business: SqlAlchemyTenantBusinessHttpRuntime
    identity: SqlAlchemyTenantIdentityHttpRuntime
    invitations: SqlAlchemyTenantInvitationHttpRuntime
    integrations: SqlAlchemyTenantIntegrationHttpRuntime
    provider_accounts: SqlAlchemyTenantProviderAccountHttpRuntime
    platform_identity: SqlAlchemyPlatformIdentityHttpRuntime
    platform_tenant_read: SqlAlchemyPlatformTenantReadHttpRuntime
    platform_subscription_adjustment: (
        SqlAlchemyPlatformSubscriptionAdjustmentHttpRuntime | None
    )
    platform_redemption: SqlAlchemyPlatformRedemptionHttpRuntime | None
    subscription: SqlAlchemyTenantSubscriptionHttpRuntime
    gantt: SqlAlchemyGanttSaasHttpRuntime
    rental: SqlAlchemyRentalSaasHttpRuntime
    inspection: SqlAlchemyInspectionSaasHttpRuntime
    warehouse: SqlAlchemyWarehouseSaasHttpRuntime
    relay: SqlAlchemyRelaySaasHttpRuntime
    sf_batch_shipping: SqlAlchemySfBatchShippingHttpRuntime
    sf_tracking: SqlAlchemySfTrackingHttpRuntime | None
    xianyu_sync: SqlAlchemyXianyuSyncHttpRuntime | None

    def __post_init__(self) -> None:
        if (
            not isinstance(
                self.tenant_business, SqlAlchemyTenantBusinessHttpRuntime
            )
            or not isinstance(
                self.identity, SqlAlchemyTenantIdentityHttpRuntime
            )
            or not isinstance(
                self.invitations, SqlAlchemyTenantInvitationHttpRuntime
            )
            or not isinstance(
                self.integrations, SqlAlchemyTenantIntegrationHttpRuntime
            )
            or not isinstance(
                self.provider_accounts,
                SqlAlchemyTenantProviderAccountHttpRuntime,
            )
            or not isinstance(
                self.subscription,
                SqlAlchemyTenantSubscriptionHttpRuntime,
            )
            or not isinstance(
                self.platform_identity,
                SqlAlchemyPlatformIdentityHttpRuntime,
            )
            or not isinstance(
                self.platform_tenant_read,
                SqlAlchemyPlatformTenantReadHttpRuntime,
            )
            or (
                self.platform_subscription_adjustment is not None
                and not isinstance(
                    self.platform_subscription_adjustment,
                    SqlAlchemyPlatformSubscriptionAdjustmentHttpRuntime,
                )
            )
            or (
                self.platform_redemption is not None
                and not isinstance(
                    self.platform_redemption,
                    SqlAlchemyPlatformRedemptionHttpRuntime,
                )
            )
            or not isinstance(self.gantt, SqlAlchemyGanttSaasHttpRuntime)
            or not isinstance(self.rental, SqlAlchemyRentalSaasHttpRuntime)
            or not isinstance(
                self.inspection, SqlAlchemyInspectionSaasHttpRuntime
            )
            or not isinstance(
                self.warehouse, SqlAlchemyWarehouseSaasHttpRuntime
            )
            or not isinstance(self.relay, SqlAlchemyRelaySaasHttpRuntime)
            or not isinstance(
                self.sf_batch_shipping,
                SqlAlchemySfBatchShippingHttpRuntime,
            )
            or self.sf_batch_shipping.control_database
            is not self.tenant_business.control_database
            or self.sf_batch_shipping.tenant_http_boundary
            is not self.tenant_business.tenant_http_boundary
            or self.sf_batch_shipping.tenant_business_runtime
            is not self.tenant_business
            or (
                self.sf_tracking is not None
                and not isinstance(
                    self.sf_tracking,
                    SqlAlchemySfTrackingHttpRuntime,
                )
            )
            or (
                self.xianyu_sync is not None
                and not isinstance(
                    self.xianyu_sync,
                    SqlAlchemyXianyuSyncHttpRuntime,
                )
            )
            or self.identity.control_database
            is not self.tenant_business.control_database
            or self.identity.tenant_http_boundary
            is not self.tenant_business.tenant_http_boundary
            or self.invitations.control_database
            is not self.tenant_business.control_database
            or self.invitations.tenant_http_boundary
            is not self.tenant_business.tenant_http_boundary
            or self.integrations.control_database
            is not self.tenant_business.control_database
            or self.integrations.tenant_http_boundary
            is not self.tenant_business.tenant_http_boundary
            or self.provider_accounts.control_database
            is not self.tenant_business.control_database
            or self.provider_accounts.tenant_http_boundary
            is not self.tenant_business.tenant_http_boundary
            or self.provider_accounts.tenant_business_runtime
            is not self.tenant_business
            or self.identity.session_service
            is not self.tenant_business.tenant_http_boundary.session_service
            or self.subscription.control_database
            is not self.tenant_business.control_database
            or self.platform_identity.control_database
            is not self.tenant_business.control_database
            or self.platform_tenant_read.control_database
            is not self.tenant_business.control_database
            or self.platform_tenant_read.platform_boundary
            is not self.platform_identity.boundary
            or (
                self.platform_subscription_adjustment is not None
                and (
                    self.platform_subscription_adjustment.control_database
                    is not self.tenant_business.control_database
                    or self.platform_subscription_adjustment.platform_boundary
                    is not self.platform_identity.boundary
                )
            )
            or (
                self.platform_redemption is not None
                and (
                    self.platform_redemption.control_database
                    is not self.tenant_business.control_database
                    or self.platform_redemption.platform_boundary
                    is not self.platform_identity.boundary
                )
            )
            or self.subscription.tenant_http_boundary
            is not self.tenant_business.tenant_http_boundary
            or self.gantt.tenant_business_runtime is not self.tenant_business
            or self.relay.tenant_business_runtime is not self.tenant_business
            or (
                self.sf_tracking is not None
                and (
                    self.sf_tracking.control_database
                    is not self.tenant_business.control_database
                    or self.sf_tracking.tenant_http_boundary
                    is not self.tenant_business.tenant_http_boundary
                    or self.sf_tracking.tenant_business_runtime
                    is not self.tenant_business
                )
            )
            or (
                self.xianyu_sync is not None
                and (
                    self.xianyu_sync.tenant_business_runtime
                    is not self.tenant_business
                    or self.xianyu_sync.job_coordinator.database
                    is not self.tenant_business.control_database
                )
            )
        ):
            raise TypeError("SaaS Core HTTP runtime bundle is invalid")


def build_saas_core_http_runtime_bundle(
    *,
    control_database: ControlDatabase,
    settings: SaasCoreHttpRuntimeSettings,
) -> SaasCoreHttpRuntimeBundle:
    """Build a complete object graph without publishing or connecting."""

    if not isinstance(control_database, ControlDatabase) or not isinstance(
        settings, SaasCoreHttpRuntimeSettings
    ):
        raise TypeError("SaaS Core HTTP runtime composition is invalid")
    shared = build_tenant_business_http_runtime(
        control_database=control_database,
        root_key_directory=settings.root_key_directory,
        database_instances=settings.database_instances,
        engine_pool_settings=settings.engine_pool_settings,
        max_cache_entries=settings.max_cache_entries,
    )
    authority_reader = SqlAlchemyGanttPreviewAuthorityReader(
        control_database=control_database,
        root_key_directory=settings.root_key_directory,
    )
    gantt = SqlAlchemyGanttSaasHttpRuntime(
        proof_adapter=GanttPreviewProofAdapter(
            authority_reader=authority_reader
        ),
        tenant_business_runtime=shared,
    )
    login_settings = settings.tenant_login
    platform_identity = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=control_database,
        root_key_directory=settings.root_key_directory,
        login_settings=settings.platform_login,
    )
    platform_read_router_scope = SqlAlchemyTenantRouterScope(
        root_key_directory=settings.root_key_directory,
        database_instances=settings.database_instances,
        engine_pool_settings=settings.engine_pool_settings,
        max_cache_entries=settings.max_cache_entries,
    )
    return SaasCoreHttpRuntimeBundle(
        tenant_business=shared,
        identity=SqlAlchemyTenantIdentityHttpRuntime(
            control_database=control_database,
            tenant_http_boundary=shared.tenant_http_boundary,
            session_service=shared.tenant_http_boundary.session_service,
            root_key_directory=settings.root_key_directory,
            sms_provider=(
                login_settings.sms_provider
                if login_settings is not None
                else None
            ),
            sms_policy=(
                login_settings.sms_policy
                if login_settings is not None
                else None
            ),
            session_policy=(
                login_settings.session_policy
                if login_settings is not None
                else None
            ),
            trusted_source_resolver=(
                login_settings.trusted_source_resolver
                if login_settings is not None
                else None
            ),
        ),
        invitations=SqlAlchemyTenantInvitationHttpRuntime(
            control_database=control_database,
            tenant_http_boundary=shared.tenant_http_boundary,
            root_key_directory=settings.root_key_directory,
            sms_provider=(
                login_settings.sms_provider
                if login_settings is not None
                else None
            ),
            sms_policy=(
                login_settings.sms_policy
                if login_settings is not None
                else None
            ),
            trusted_source_resolver=(
                login_settings.trusted_source_resolver
                if login_settings is not None
                else None
            ),
        ),
        integrations=SqlAlchemyTenantIntegrationHttpRuntime(
            control_database=control_database,
            tenant_http_boundary=shared.tenant_http_boundary,
            root_key_directory=settings.root_key_directory,
            sms_provider=(
                login_settings.sms_provider
                if login_settings is not None
                else None
            ),
            sms_policy=(
                login_settings.sms_policy
                if login_settings is not None
                else None
            ),
            trusted_source_resolver=(
                login_settings.trusted_source_resolver
                if login_settings is not None
                else None
            ),
        ),
        provider_accounts=SqlAlchemyTenantProviderAccountHttpRuntime(
            control_database=control_database,
            tenant_http_boundary=shared.tenant_http_boundary,
            tenant_business_runtime=shared,
            root_key_directory=settings.root_key_directory,
            sms_provider=(
                login_settings.sms_provider
                if login_settings is not None
                else None
            ),
            sms_policy=(
                login_settings.sms_policy
                if login_settings is not None
                else None
            ),
            trusted_source_resolver=(
                login_settings.trusted_source_resolver
                if login_settings is not None
                else None
            ),
        ),
        platform_identity=platform_identity,
        platform_tenant_read=SqlAlchemyPlatformTenantReadHttpRuntime(
            control_database=control_database,
            platform_boundary=platform_identity.boundary,
            tenant_router_factory=platform_read_router_scope,
            read_policy_version=settings.platform_read_policy_version,
            maximum_execution_time_ms=(
                settings.platform_read_query_timeout_ms
            ),
        ),
        platform_subscription_adjustment=(
            SqlAlchemyPlatformSubscriptionAdjustmentHttpRuntime(
                control_database=control_database,
                platform_boundary=platform_identity.boundary,
                root_key_directory=settings.root_key_directory,
                login_settings=settings.platform_login,
                runtime_settings=settings.platform_redemption,
            )
            if (
                settings.platform_login is not None
                and settings.platform_redemption is not None
            )
            else None
        ),
        platform_redemption=(
            SqlAlchemyPlatformRedemptionHttpRuntime(
                control_database=control_database,
                platform_boundary=platform_identity.boundary,
                root_key_directory=settings.root_key_directory,
                login_settings=settings.platform_login,
            )
            if settings.platform_login is not None
            else None
        ),
        subscription=SqlAlchemyTenantSubscriptionHttpRuntime(
            control_database=control_database,
            tenant_http_boundary=shared.tenant_http_boundary,
        ),
        gantt=gantt,
        rental=SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=shared
        ),
        inspection=SqlAlchemyInspectionSaasHttpRuntime(
            tenant_business_runtime=shared
        ),
        warehouse=SqlAlchemyWarehouseSaasHttpRuntime(
            tenant_business_runtime=shared
        ),
        relay=SqlAlchemyRelaySaasHttpRuntime(
            tenant_business_runtime=shared
        ),
        sf_batch_shipping=SqlAlchemySfBatchShippingHttpRuntime(
            control_database=control_database,
            tenant_http_boundary=shared.tenant_http_boundary,
            tenant_business_runtime=shared,
        ),
        sf_tracking=(
            SqlAlchemySfTrackingHttpRuntime(
                control_database=control_database,
                tenant_http_boundary=shared.tenant_http_boundary,
                tenant_business_runtime=shared,
                root_key_directory=settings.root_key_directory,
                adapter=settings.sf_tracking_adapter,
            )
            if settings.sf_tracking_adapter is not None
            else None
        ),
        xianyu_sync=(
            SqlAlchemyXianyuSyncHttpRuntime(
                tenant_business_runtime=shared,
                job_coordinator=XianyuSyncJobCoordinator(
                    database=control_database,
                    gate=settings.xianyu_schedule_gate,
                ),
            )
            if settings.xianyu_schedule_gate is not None
            else None
        ),
    )


def install_saas_core_http_runtime_bundle(
    app: Flask,
    *,
    settings: SaasCoreHttpRuntimeSettings,
) -> SaasCoreHttpRuntimeBundle:
    """Build first and publish every runtime in one dictionary update."""

    if not isinstance(app, Flask):
        raise TypeError("app must be a Flask application")
    if any(key in app.extensions for key in _RUNTIME_EXTENSION_KEYS):
        raise RuntimeError("a SaaS Core HTTP runtime is already installed")
    control_database = app.extensions.get(CONTROL_DATABASE_EXTENSION)
    if not isinstance(control_database, ControlDatabase):
        raise RuntimeError("control database is not installed")
    bundle = build_saas_core_http_runtime_bundle(
        control_database=control_database,
        settings=settings,
    )
    extensions = {
        TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION: bundle.tenant_business,
        TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION: bundle.identity,
        TENANT_INVITATION_HTTP_RUNTIME_EXTENSION: bundle.invitations,
        TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION: bundle.integrations,
        TENANT_PROVIDER_ACCOUNT_HTTP_RUNTIME_EXTENSION: (
            bundle.provider_accounts
        ),
        PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION: bundle.platform_identity,
        PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION: bundle.platform_tenant_read,
        TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION: bundle.subscription,
        GANTT_SAAS_HTTP_RUNTIME_EXTENSION: bundle.gantt,
        RENTAL_SAAS_HTTP_RUNTIME_EXTENSION: bundle.rental,
        INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION: bundle.inspection,
        WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION: bundle.warehouse,
        RELAY_SAAS_HTTP_RUNTIME_EXTENSION: bundle.relay,
        SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION: bundle.sf_batch_shipping,
    }
    if bundle.platform_subscription_adjustment is not None:
        extensions[
            PLATFORM_SUBSCRIPTION_ADJUSTMENT_HTTP_RUNTIME_EXTENSION
        ] = bundle.platform_subscription_adjustment
    if bundle.platform_redemption is not None:
        extensions[PLATFORM_REDEMPTION_HTTP_RUNTIME_EXTENSION] = (
            bundle.platform_redemption
        )
    if bundle.sf_tracking is not None:
        extensions[SF_TRACKING_HTTP_RUNTIME_EXTENSION] = bundle.sf_tracking
    if bundle.xianyu_sync is not None:
        extensions[XIANYU_SYNC_HTTP_RUNTIME_EXTENSION] = bundle.xianyu_sync
    app.extensions.update(extensions)
    return bundle


def install_configured_saas_core_http_runtimes(
    app: Flask,
) -> SaasCoreHttpRuntimeBundle | None:
    """Honor one explicit enable switch; absent settings never imply authority."""

    if not isinstance(app, Flask):
        raise TypeError("app must be a Flask application")
    enabled = app.config.get(ENABLE_SAAS_CORE_HTTP_RUNTIME, False)
    if enabled is not True:
        return None
    settings = app.config.get(SAAS_CORE_HTTP_RUNTIME_SETTINGS)
    if not isinstance(settings, SaasCoreHttpRuntimeSettings):
        raise RuntimeError("SaaS Core HTTP runtime settings are missing")
    return install_saas_core_http_runtime_bundle(app, settings=settings)


__all__ = [
    "ENABLE_SAAS_CORE_HTTP_RUNTIME",
    "SAAS_CORE_HTTP_RUNTIME_SETTINGS",
    "SaasCoreHttpRuntimeBundle",
    "SaasCoreHttpRuntimeSettings",
    "build_saas_core_http_runtime_bundle",
    "install_configured_saas_core_http_runtimes",
    "install_saas_core_http_runtime_bundle",
]
