"""型号租赁组合与旧镜头组合的兼容规则。"""

from copy import deepcopy
import json

from app.lens_combos import compatibility_lens_combo_config


LEGACY_PACKAGE_PREFIX = "legacy_"

LEGACY_PACKAGE_DEFINITIONS = {
    "lens_400mm": {
        "name": "400MM 镜头",
        "items": [
            {"name": "90w 充电头+充电线", "qty": 1},
            {"name": "400MM 增距镜+增距镜脚架+手机壳", "qty": 1},
            {"name": "套装便携手提包", "qty": 1},
        ],
    },
    "lens_200mm": {
        "name": "200MM 镜头",
        "items": [
            {"name": "90w 充电头+充电线", "qty": 1},
            {"name": "200MM 镜头+手机壳", "qty": 1},
            {"name": "套装便携手提包", "qty": 1},
        ],
    },
    "bare": {
        "name": "裸机",
        "items": [
            {"name": "90w 充电头+充电线", "qty": 1},
        ],
    },
    "lens_dual": {
        "name": "双镜头",
        "items": [
            {"name": "90w 充电头+充电线", "qty": 1},
            {"name": "400MM 增距镜+增距镜脚架+手机壳", "qty": 1},
            {"name": "200MM 镜头", "qty": 1},
            {"name": "套装便携手提包", "qty": 1},
        ],
    },
}


def legacy_package_id(lens_combo):
    """为历史枚举生成稳定的型号组合 ID。"""
    return f"{LEGACY_PACKAGE_PREFIX}{lens_combo}"


def legacy_package(lens_combo, *, enabled=True):
    """把一个历史镜头枚举转换为完整租赁组合。"""
    definition = LEGACY_PACKAGE_DEFINITIONS.get(lens_combo)
    if definition is None:
        definition = {"name": str(lens_combo or "未命名组合"), "items": []}
    return {
        "id": legacy_package_id(lens_combo or "unknown"),
        "name": definition["name"],
        "is_active": bool(enabled),
        "items": deepcopy(definition["items"]),
    }


def legacy_packages(lens_combos):
    """按旧配置顺序生成组合列表，并去除重复项。"""
    result = []
    seen = set()
    for combo in lens_combos or []:
        if not isinstance(combo, str) or combo in seen:
            continue
        seen.add(combo)
        result.append(legacy_package(combo))
    return result


def compatibility_rental_package_config(model_name=None, allowed=None, default=None):
    """返回旧型号可直接迁移使用的组合列表和默认组合 ID。"""
    fallback_allowed, fallback_default = compatibility_lens_combo_config(model_name)
    allowed = list(allowed or fallback_allowed)
    default = default if default in allowed else fallback_default
    if default not in allowed and allowed:
        default = allowed[0]
    return legacy_packages(allowed), legacy_package_id(default)


def parse_rental_packages(raw_value):
    """解析型号组合 JSON；非法值返回空列表。"""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [deepcopy(item) for item in parsed if isinstance(item, dict)]


def parse_package_items(raw_value):
    """解析订单保存的组合物品快照；非法值返回空列表。"""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    result = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        qty = item.get("qty")
        if isinstance(name, str) and name.strip() and isinstance(qty, int) and qty > 0:
            result.append({"name": name.strip(), "qty": qty})
    return result


def serialize_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
