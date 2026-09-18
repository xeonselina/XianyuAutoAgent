"""Shared thermal renderer must not retain another tenant's branding."""

import base64
import importlib
import io
from types import SimpleNamespace

from flask import Flask, g
from PIL import Image


def test_shared_renderer_uses_each_request_tenant_name(monkeypatch):
    module = importlib.import_module('app.services.printing.shipping_slip_image_service')
    groups = importlib.import_module('app.services.shipping.shipment_group_service')
    rental = SimpleNamespace(
        id=42, customer_name='测试客户', device=None,
        ship_out_tracking_no=None, end_date=None,
        get_all_accessories_for_display=lambda: [],
    )
    monkeypatch.setattr(module, 'db', SimpleNamespace(
        session=SimpleNamespace(get=lambda *_: rental),
    ))
    monkeypatch.setattr(module, 'rental_package_display', lambda _: '测试组合')
    monkeypatch.setattr(groups, 'parcel_members', lambda _: [rental])
    service = module.shipping_slip_image_service
    monkeypatch.setattr(service, '_draw_qr_codes_section', lambda img, y: y)
    drawn = []
    original_text = module.ImageDraw.ImageDraw.text

    def capture_text(draw, xy, text, *args, **kwargs):
        drawn.append(text)
        return original_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(module.ImageDraw.ImageDraw, 'text', capture_text)
    app = Flask(__name__)
    for name in ('光影租界', '远山摄影器材租赁', '很长的摄影器材租赁店铺名称用于检查换行'):
        drawn.clear()
        with app.test_request_context():
            g.tenant = SimpleNamespace(name=name)
            encoded = service.generate_slip_image(42)
        header_end = drawn.index('R-42')
        assert ''.join(drawn[:header_end]) == name
        for line in drawn[:header_end]:
            bounds = service.font_large.getbbox(line)
            assert bounds[2] - bounds[0] <= service.width_px - 2 * service.padding
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as result:
            assert result.width == service.width_px

    drawn.clear()
    with app.test_request_context():
        service.generate_slip_image(42)
    assert drawn[:2] == ['发货单', 'R-42']
