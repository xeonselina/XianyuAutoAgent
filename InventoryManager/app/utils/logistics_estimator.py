"""顺丰标快物流时效预估。

规则与 ``ai_kefu/tools/calculate_logistics.py`` 保持一致：从广东深圳发出，
根据收货地址中的省份或城市名称估算运输天数。
"""

from typing import Any, Dict


DEFAULT_LOGISTICS_DAYS = 3

_LOCATIONS_BY_DAYS = {
    1: (
        '广东', '深圳', '广州', '东莞', '佛山', '珠海', '中山', '惠州',
        '江门', '肇庆', '汕头', '湛江', '韶关', '河源', '梅州', '清远',
        '阳江', '潮州', '揭阳', '云浮', '汕尾',
    ),
    2: (
        '福建', '福州', '厦门', '泉州', '湖南', '长沙', '湖北', '武汉',
        '江西', '南昌', '浙江', '杭州', '宁波', '温州', '上海', '江苏',
        '南京', '苏州', '无锡', '常州', '广西', '南宁', '桂林', '海南',
        '海口', '三亚',
    ),
    3: (
        '北京', '天津', '河北', '石家庄', '山东', '济南', '青岛', '河南',
        '郑州', '安徽', '合肥', '四川', '成都', '重庆', '贵州', '贵阳',
        '云南', '昆明', '山西', '太原', '陕西', '西安',
    ),
    4: (
        '辽宁', '沈阳', '大连', '吉林', '长春', '黑龙江', '哈尔滨', '甘肃',
        '兰州', '青海', '西宁', '宁夏', '银川', '内蒙古', '呼和浩特',
    ),
    6: ('新疆', '乌鲁木齐'),
    7: ('西藏', '拉萨'),
}

LOGISTICS_DAYS_MAP = {
    location: days
    for days, locations in _LOCATIONS_BY_DAYS.items()
    for location in locations
}

# 长名称优先，避免较短的地区名称抢先匹配。
_SORTED_LOCATIONS = sorted(LOGISTICS_DAYS_MAP, key=len, reverse=True)


def estimate_sf_logistics(destination: str) -> Dict[str, Any]:
    """根据收货地址预估从深圳发出的顺丰标快运输天数。"""
    normalized_destination = (destination or '').strip()
    if not normalized_destination:
        raise ValueError('目的地地址不能为空')

    matched_location = next(
        (location for location in _SORTED_LOCATIONS if location in normalized_destination),
        None,
    )
    logistics_days = (
        LOGISTICS_DAYS_MAP[matched_location]
        if matched_location
        else DEFAULT_LOGISTICS_DAYS
    )

    if matched_location:
        message = (
            f'从深圳寄往 {matched_location} 预计 {logistics_days} 天送达'
            '（顺丰标快）'
        )
    else:
        message = (
            f'未找到精确匹配地区，按默认 {logistics_days} 天计算'
            '（顺丰标快）'
        )

    return {
        'logistics_days': logistics_days,
        'destination': normalized_destination,
        'matched_location': matched_location,
        'shipping_method': '顺丰标快',
        'origin': '广东深圳',
        'message': message,
    }

