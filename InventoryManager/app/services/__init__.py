"""
服务层包
"""

from .inventory_service import InventoryService
from .rental_service import RentalService
from .printing.shipping_slip_image_service import shipping_slip_image_service

__all__ = ['InventoryService', 'RentalService', 'shipping_slip_image_service']
