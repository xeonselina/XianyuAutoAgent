"""Canaries for integration payload and error redaction."""

import json
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
import requests

from app.auth import TencentSmsSender, mask_phone
from app.services.printing import shipping_slip_image_service as slip_module; from app.services.shipping import pdf_conversion_service as pdf_module
from app.services.printing.kuaimai_service import KuaimaiPrintService, KuaimaiServiceConfig
from app.services.shipping.sf_express_service import SFExpressService, SFServiceConfig
from app.services.xianyu_order_service import XianyuOrderService, XianyuOrderServiceError, XianyuShopConfig
from app.utils.sf.sf_sdk_wrapper import SFExpressSDK


def assert_hidden(text, *canaries):
    assert not any(value in text for value in canaries)


@pytest.mark.parametrize(("failure", "code"), [("http", "A9999"), ("json", "A9998"), ("exception", "A9997")])
def test_sf_keeps_success_payload_but_redacts_requests_and_errors(monkeypatch, caplog, failure, code):
    service = SFExpressService(SFServiceConfig(
        "SF-PARTNER", "SF-CHECKWORD", "SF-CARD", True, "SF-SENDER",
        "13800138000", "SF-ADDRESS", "广东省", "深圳市",
    ))
    rental = SimpleNamespace(
        id=7, customer_name="SF-RECEIVER", customer_phone="13900139000",
        destination="SF-RECEIVER 13900139000 SF-DEST", express_type_id=2, device=None,
    )
    monkeypatch.setattr(service, "create_order", lambda _: {"success": True, "waybill_no": "SF-WAYBILL"})

    class Response:
        status_code = 500 if failure == "http" else 200

        def raise_for_status(self):
            if failure == "http":
                raise requests.HTTPError("SF-UPSTREAM")

        def json(self):
            if failure == "json":
                raise json.JSONDecodeError("bad", "SF-UPSTREAM", 0)
            raise RuntimeError("SF-UPSTREAM")

    sdk = SFExpressSDK("SF-PARTNER", "SF-CHECKWORD")
    monkeypatch.setattr("app.utils.sf.sf_sdk_wrapper.requests.post", lambda *_a, **_k: Response())
    with caplog.at_level(logging.DEBUG):
        success = service.place_shipping_order(rental, datetime(2026, 8, 25, 10), "SF-CLIENT")
        failed = sdk._call_sf_express_service("EXP_RECE_CREATE_ORDER", {"secret": "SF-PAYLOAD"})
    assert success["waybill_no"] == "SF-WAYBILL"
    assert failed["apiResultCode"] == code
    assert_hidden(caplog.text + str(failed), "SF-PARTNER", "SF-CHECKWORD", "SF-CARD",
                  "SF-SENDER", "13800138000", "SF-ADDRESS", "SF-RECEIVER",
                  "13900139000", "SF-DEST", "SF-PAYLOAD", "SF-UPSTREAM")

    monkeypatch.setattr(sdk, "_call_sf_express_service",
                        lambda *_: {"apiResultCode": "E1", "apiErrorMsg": "SF-UPSTREAM"})
    assert sdk.create_order({}) == {
        "success": False, "message": "顺丰服务调用失败", "code": "E1",
    }


def test_kuaimai_keeps_job_id_but_redacts_request_and_failure(monkeypatch, caplog):
    service = KuaimaiPrintService(KuaimaiServiceConfig("KM-APP", "KM-SECRET", "KM-SN"))
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"status": True, "data": {
            "jobId": "KM-JOB", "status": "completed", "message": "KM-UPSTREAM"}},
    )
    monkeypatch.setattr("app.services.printing.kuaimai_service.requests.post", lambda *_a, **_k: response)
    with caplog.at_level(logging.DEBUG):
        assert service.print_image("KM-IMAGE")["job_id"] == "KM-JOB"
        status = service.get_print_status("KM-JOB")
    assert status["status"] == "completed"
    assert_hidden(caplog.text + str(status), "KM-APP", "KM-SECRET", "KM-SN", "KM-IMAGE",
                  "KM-JOB", "KM-UPSTREAM", "生成签名:")

    monkeypatch.setattr(service, "_make_request", lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("KM-UPSTREAM")))
    caplog.clear()
    failed = service.get_print_status("KM-JOB")
    assert failed == {"status": "error", "message": "快麦打印服务调用失败"}
    assert_hidden(caplog.text + str(failed), "KM-UPSTREAM", "KM-JOB")


def test_xianyu_keeps_detail_but_redacts_orders_and_upstream_errors(monkeypatch, caplog):
    service = XianyuOrderService(XianyuShopConfig(1, "XY-APP", "XY-SECRET"), "open.goofish.pro")
    detail = {"receiver_mobile": "13700137000", "address": "XY-ADDRESS"}
    monkeypatch.setattr(service, "_request_with_body_sign", lambda path, _body:
                        {"code": 0, "data": detail} if path.endswith("detail")
                        else {"code": "E1", "msg": "XY-UPSTREAM"})
    rental = SimpleNamespace(id=9, xianyu_order_no="XY-ORDER", ship_out_tracking_no="XY-WAYBILL")
    with caplog.at_level(logging.DEBUG):
        assert service.get_order_detail("XY-ORDER") == detail
        shipped = service.ship_order(rental)
        with pytest.raises(XianyuOrderServiceError) as error_info:
            service.list_orders()
    assert shipped == {"success": False, "message": "闲鱼发货失败", "code": "E1"}
    assert str(error_info.value) == "闲鱼订单列表查询失败"
    assert_hidden(caplog.text + str(shipped) + str(error_info.value), "XY-UPSTREAM",
                  "XY-ORDER", "XY-WAYBILL", "13700137000", "XY-ADDRESS")


def test_sms_masks_only_valid_phone_and_redacts_transport_exception(caplog):
    assert mask_phone("+8613800138000") == "+86138****8000"
    assert {mask_phone(value) for value in ("", "123", None)} == {"[hidden]"}
    client = SimpleNamespace(SendSms=lambda _request: (_ for _ in ()).throw(
        RuntimeError("SMS-UPSTREAM")))
    sender = TencentSmsSender("id", "key", "app", "sign", "template", client=client)
    with pytest.raises(RuntimeError, match="^短信服务调用失败$") as error_info:
        sender.send_code("+8613800138000", "123456", 5)
    assert_hidden(caplog.text + str(error_info.value), "SMS-UPSTREAM", "123456")

def test_pdf_and_slip_errors_are_fixed_and_redacted(monkeypatch, caplog):
    canary = "RENDER-ERROR-CANARY"; boom = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(canary))
    pdf = pdf_module.PDFConversionService(); monkeypatch.setattr(pdf, "convert_pdf_to_images", boom)
    with caplog.at_level(logging.ERROR), pytest.raises(pdf_module.PDFConversionError) as pdf_error: pdf.convert_pdf_to_base64_images(b"pdf")
    monkeypatch.setattr(slip_module, "db", SimpleNamespace(session=SimpleNamespace(get=boom)))
    with pytest.raises(slip_module.SlipGenerationError) as slip_error: object.__new__(slip_module.ShippingSlipImageService).generate_slip_image(9)
    assert (str(pdf_error.value), str(slip_error.value)) == ("PDF转base64流程失败", "生成发货单图像失败"); assert_hidden(caplog.text, canary, "Traceback")
