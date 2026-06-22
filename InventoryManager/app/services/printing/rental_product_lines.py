"""
租赁品名清单渲染服务

根据租赁记录的机型 + lens_combo，生成发货单/面单的品名行。
同时提供镜头组合的合法性校验与中文化展示。
"""

# 各机型允许的镜头组合及默认值
# 命名严格对齐 rentals.lens_combo Enum
MODEL_LENS_COMBOS = {
    'x200u':   {'allowed': ('lens_200mm', 'bare'),                              'default': 'lens_200mm'},
    'x300pro': {'allowed': ('lens_200mm', 'bare'),                              'default': 'lens_200mm'},
    'x300u':   {'allowed': ('lens_400mm', 'lens_200mm', 'bare', 'lens_dual'),   'default': 'lens_400mm'},
}

# 机型 -> 主机品名中文显示
MODEL_DISPLAY = {
    'x200u':   'VIVO X200 Ultra 16+512G',
    'x300pro': 'VIVO X300 Pro',
    'x300u':   'VIVO X300 Ultra',
}

# lens_combo -> 中文（用于 tooltip、客户历史明细）
LENS_COMBO_DISPLAY = {
    'lens_400mm': '400MM 镜头',
    'lens_200mm': '200MM 镜头',
    'bare':       '裸机',
    'lens_dual':  '双镜头',
}


def get_allowed_combos(model_name):
    """返回指定机型允许的镜头组合列表。未知机型回退到 x200u 的可选集。"""
    cfg = MODEL_LENS_COMBOS.get(model_name)
    if not cfg:
        return list(MODEL_LENS_COMBOS['x200u']['allowed'])
    return list(cfg['allowed'])


def get_default_combo(model_name):
    """返回指定机型的默认镜头组合。"""
    cfg = MODEL_LENS_COMBOS.get(model_name)
    if not cfg:
        return 'lens_200mm'
    return cfg['default']


def validate_combo(model_name, lens_combo):
    """校验「机型-镜头组合」是否合法。"""
    if not model_name:
        return False
    cfg = MODEL_LENS_COMBOS.get(model_name)
    if not cfg:
        return False
    return lens_combo in cfg['allowed']


def lens_combo_display(lens_combo):
    """镜头组合中文化。"""
    return LENS_COMBO_DISPLAY.get(lens_combo, lens_combo or '')


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


def _resolve_model_display(model_name):
    return MODEL_DISPLAY.get(model_name, model_name or '主机')


def get_product_lines(rental):
    """
    根据机型 + 镜头组合返回品名清单。

    Returns:
        list[dict]: 每项含 {'name': str, 'qty': int, 'is_main': bool}
    """
    model_name = _resolve_model_name(rental)
    combo = getattr(rental, 'lens_combo', None) or get_default_combo(model_name)

    lines = [
        {'name': _resolve_model_display(model_name), 'qty': 1, 'is_main': True},
        {'name': '90w 充电头+充电线', 'qty': 1, 'is_main': False},
    ]

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
