"""
租赁品名清单渲染服务

优先根据订单保存的自由租赁组合快照生成发货清单；旧订单继续使用
机型 + lens_combo 的兼容规则。
"""

from app.lens_combos import (
    LENS_COMBO_DISPLAY,
    compatibility_lens_combo_config,
    normalize_legacy_model_name,
)

# 机型 -> 主机品名中文显示
MODEL_DISPLAY = {
    'x200u':   'VIVO X200 Ultra 16+512G',
    'x300pro': 'VIVO X300 Pro',
    'x300u':   'VIVO X300 Ultra',
}

def normalize_model_name(model_name):
    """将数据库机型名（如 'VIVO X300U 16+512'）归一化为配置 key（x200u/x300pro/x300u）。

    注意 x300pro 必须先于 x300u 判断，否则 'X300PRO' 会被 'x300' 误命中。
    无法识别时返回 None。
    """
    return normalize_legacy_model_name(model_name)


def get_allowed_combos(model_name):
    """返回指定机型允许的镜头组合列表。未知机型回退到 x200u 的可选集。"""
    return compatibility_lens_combo_config(model_name)[0]


def get_default_combo(model_name):
    """返回指定机型的默认镜头组合。"""
    return compatibility_lens_combo_config(model_name)[1]


def validate_combo(model_name, lens_combo):
    """校验「机型-镜头组合」是否合法。"""
    return lens_combo in get_allowed_combos(model_name)


def lens_combo_display(lens_combo):
    """镜头组合中文化。"""
    return LENS_COMBO_DISPLAY.get(lens_combo, lens_combo or '')


def rental_package_display(rental):
    """返回订单组合名称；没有新快照时回退到旧枚举显示。"""
    package_name = getattr(rental, 'rental_package_name', None)
    if package_name:
        return package_name
    combo = getattr(rental, 'lens_combo', None)
    return lens_combo_display(combo)


def _resolve_model_name(rental):
    """从 rental 解析出机型 short name (e.g. 'x300u')。"""
    device = getattr(rental, 'device', None)
    if device is None:
        return None
    # 优先 device_model.name；回退 device.model
    dm = getattr(device, 'device_model', None)
    if dm and getattr(dm, 'name', None):
        return dm.name
    return getattr(device, 'model', None)


def _resolve_model_display(rental, model_name):
    device = getattr(rental, 'device', None)
    device_model = getattr(device, 'device_model', None) if device else None
    if device_model and getattr(device_model, 'display_name', None):
        return device_model.display_name
    normalized = normalize_model_name(model_name)
    return MODEL_DISPLAY.get(normalized, model_name or '主机')


def get_product_lines(rental):
    """
    根据机型 + 镜头组合返回品名清单。

    Returns:
        list[dict]: 每项含 {'name': str, 'qty': int, 'is_main': bool}
    """
    model_name = _resolve_model_name(rental)
    combo = getattr(rental, 'lens_combo', None) or get_default_combo(model_name)

    lines = [
        {'name': _resolve_model_display(rental, model_name), 'qty': 1, 'is_main': True},
    ]

    snapshot = getattr(rental, 'get_rental_package_snapshot', lambda: None)()
    if snapshot:
        lines.extend(
            {'name': item['name'], 'qty': item['qty'], 'is_main': False}
            for item in snapshot.get('items', [])
        )
        return lines

    lines.append({'name': '90w 充电头+充电线', 'qty': 1, 'is_main': False})

    if combo == 'lens_400mm':
        lines.append({'name': '400MM 增距镜+增距镜脚架+手机壳', 'qty': 1, 'is_main': False})
    elif combo == 'lens_200mm':
        lines.append({'name': '200MM 镜头+手机壳', 'qty': 1, 'is_main': False})
    elif combo == 'lens_dual':
        lines.append({'name': '400MM 增距镜+增距镜脚架+手机壳', 'qty': 1, 'is_main': False})
        lines.append({'name': '200MM 镜头', 'qty': 1, 'is_main': False})
    # bare: 不追加镜头行

    if combo != 'bare':
        lines.append({'name': '套装便携手提包', 'qty': 1, 'is_main': False})

    return lines
