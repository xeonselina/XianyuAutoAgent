"""
数据模型包
"""

from .device import Device
from .rental import Rental
from .audit_log import AuditLog
from .device_model import DeviceModel
from .rental_statistics import RentalStatistics
from .inspection_record import InspectionRecord
from .inspection_check_item import InspectionCheckItem
from .rental_relay_binding import RentalRelayBinding
from .rental_relay_case import RentalRelayCase
from .xianyu_order_alert import (
    XianyuConnectionSyncState,
    XianyuOrderAlert,
    XianyuOrderSyncState,
)
from .database_identity import TenantDatabaseIdentity
from .warehouse import (
    DeviceWarehouseMovement,
    UserWarehousePreference,
    Warehouse,
    WarehousePrinter,
    WarehouseProviderBinding,
)
from .accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    DeviceAccessoryConfig,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from .shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from .legacy_unattributed_history import (
    LEGACY_UNATTRIBUTED_KIND,
    LegacyUnattributedPrintSnapshot,
    LegacyUnattributedShipmentSnapshot,
)

__all__ = [
    'Device', 'Rental', 'AuditLog', 'DeviceModel', 'RentalStatistics',
    'InspectionRecord', 'InspectionCheckItem', 'RentalRelayBinding',
    'RentalRelayCase',
    'XianyuConnectionSyncState', 'XianyuOrderAlert', 'XianyuOrderSyncState',
    'TenantDatabaseIdentity',
    'Warehouse', 'WarehousePrinter', 'UserWarehousePreference',
    'WarehouseProviderBinding', 'DeviceWarehouseMovement',
    'AccessoryType', 'DeviceAccessoryConfig', 'AccessoryUnit',
    'RentalAccessoryRequest', 'RentalAccessoryUnitLink', 'AccessoryUnitEvent',
    'OutboundShipment', 'ProviderOperationAttempt', 'WaybillPrintJob',
    'LEGACY_UNATTRIBUTED_KIND', 'LegacyUnattributedPrintSnapshot',
    'LegacyUnattributedShipmentSnapshot'
]
