import json

from app.utils.sf.sf_sdk_wrapper import SFExpressSDK


def sf_response(routes):
    return {
        "apiResultCode": "A1000",
        "apiResultData": json.dumps({
            "success": True,
            "msgData": {
                "routeResps": [{
                    "mailNo": "SF123",
                    "routes": routes,
                }],
            },
        }),
    }


def test_parser_keeps_specific_sf_status_for_unmapped_code():
    sdk = SFExpressSDK("partner", "checkword")

    result = sdk.parse_route_response(sf_response([{
        "acceptTime": "2026-08-16 12:00:00",
        "acceptAddress": "杭州市",
        "remark": "客户要求改派到新地址",
        "opCode": "999",
        "firstStatusCode": "9",
        "firstStatusName": "转寄处理中",
        "secondaryStatusCode": "901",
        "secondaryStatusName": "客户要求改派",
    }]))["SF123"]

    assert result["status"] == "processing"
    assert result["status_text"] == "客户要求改派"
    assert result["status_text"] != "未知"
    assert result["latest_route"]["remark"] == "客户要求改派到新地址"


def test_parser_uses_route_remark_when_status_names_are_missing():
    sdk = SFExpressSDK("partner", "checkword")

    result = sdk.parse_route_response(sf_response([{
        "acceptTime": "2026-08-16 13:00:00",
        "acceptAddress": "杭州中转场",
        "remark": "快件已到达杭州中转场",
        "opCode": "998",
        "firstStatusCode": "9",
    }]))["SF123"]

    assert result["status"] == "in_transit"
    assert result["status_text"] == "快件已到达杭州中转场"


def test_specific_exception_overrides_coarse_delivery_status():
    sdk = SFExpressSDK("partner", "checkword")

    result = sdk.parse_route_response(sf_response([{
        "acceptTime": "2026-08-16 14:00:00",
        "acceptAddress": "上海市",
        "remark": "派送失败，收件地址无法进入",
        "opCode": "999",
        "firstStatusCode": "3",
        "firstStatusName": "派送中",
        "secondaryStatusName": "派送失败",
    }]))["SF123"]

    assert result["status"] == "exception"
    assert result["status_text"] == "派送失败"


def test_parser_uses_clear_empty_state_when_sf_returns_no_routes():
    sdk = SFExpressSDK("partner", "checkword")

    result = sdk.parse_route_response(sf_response([]))["SF123"]

    assert result["status"] == "processing"
    assert result["status_text"] == "暂无轨迹"
    assert result["routes"] == []
