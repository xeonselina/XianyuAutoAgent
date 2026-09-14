"""镜头组合的稳定枚举与旧数据兼容规则。"""

import json


LENS_COMBO_VALUES = (
    "lens_400mm",
    "lens_200mm",
    "bare",
    "lens_dual",
)

LENS_COMBO_DISPLAY = {
    "lens_400mm": "400MM 镜头",
    "lens_200mm": "200MM 镜头",
    "bare": "裸机",
    "lens_dual": "双镜头",
}

DEFAULT_ALLOWED_LENS_COMBOS = ("lens_200mm", "bare")
DEFAULT_LENS_COMBO = "lens_200mm"
X300U_ALLOWED_LENS_COMBOS = LENS_COMBO_VALUES
X300U_DEFAULT_LENS_COMBO = "lens_400mm"


def normalize_legacy_model_name(model_name):
    """仅用于尚未归类到型号库的旧设备。"""
    if not model_name:
        return None
    normalized = str(model_name).lower().replace(" ", "").replace("+", "")
    if "x300pro" in normalized:
        return "x300pro"
    if "x300u" in normalized:
        return "x300u"
    if "x200u" in normalized:
        return "x200u"
    return None


def compatibility_lens_combo_config(model_name=None):
    """返回旧型号的兼容配置；正式型号应读取数据库字段。"""
    if normalize_legacy_model_name(model_name) == "x300u":
        return list(X300U_ALLOWED_LENS_COMBOS), X300U_DEFAULT_LENS_COMBO
    return list(DEFAULT_ALLOWED_LENS_COMBOS), DEFAULT_LENS_COMBO


def parse_allowed_lens_combos(raw_value):
    """解析数据库 JSON 文本；非法或空值返回空列表。"""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]
