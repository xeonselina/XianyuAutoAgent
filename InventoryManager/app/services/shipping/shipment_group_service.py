"""Tenant-local parcel grouping; confirmed parcels are identified by waybill."""
import re
from collections import OrderedDict
from app.models.rental import Rental
from app.services.shipping.sf_express_service import SFExpressService


def shipment_key(rental):
    if rental.ship_out_tracking_no:
        return ('waybill', rental.warehouse_id, rental.ship_out_tracking_no.strip())
    recipient = SFExpressService._parse_destination(rental.destination or '')
    address = re.sub(r'\s+', '', recipient.get('address') or rental.destination or '')
    phone = re.sub(r'[\s()-]+', '', recipient.get('phone') or rental.customer_phone or '')
    if not address or not phone or rental.parent_rental_id or rental.status != 'not_shipped':
        return ('single', rental.id)
    day = rental.ship_out_time.date() if rental.ship_out_time else rental.start_date
    return ('pending', rental.warehouse_id, rental.express_type_id or 2, day, address, phone)


def group_shipments(rentals, excluded_ids=()):
    groups = OrderedDict()
    for rental in sorted(rentals, key=lambda r: r.id):
        key = ('single', rental.id) if rental.id in excluded_ids else shipment_key(rental)
        groups.setdefault(key, []).append(rental)
    return list(groups.values())


def parcel_members(rental):
    if not rental.ship_out_tracking_no:
        return [rental]
    return Rental.query.filter_by(
        warehouse_id=rental.warehouse_id,
        ship_out_tracking_no=rental.ship_out_tracking_no,
        parent_rental_id=None,
    ).order_by(Rental.id).all()
