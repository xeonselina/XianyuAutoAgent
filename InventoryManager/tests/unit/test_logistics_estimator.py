"""顺丰标快物流时效预估测试。"""

import pytest

from app.utils.logistics_estimator import estimate_sf_logistics


@pytest.mark.parametrize(
    ('destination', 'expected_days', 'expected_location'),
    [
        ('广东省深圳市南山区', 1, '广东'),
        ('浙江省杭州市西湖区', 2, '浙江'),
        ('北京市朝阳区', 3, '北京'),
        ('黑龙江省哈尔滨市', 4, '黑龙江'),
        ('新疆乌鲁木齐市', 6, '乌鲁木齐'),
        ('西藏自治区拉萨市', 7, '西藏'),
    ],
)
def test_estimate_sf_logistics_matches_configured_location(
    destination, expected_days, expected_location
):
    result = estimate_sf_logistics(destination)

    assert result['logistics_days'] == expected_days
    assert result['matched_location'] == expected_location
    assert result['origin'] == '广东深圳'
    assert result['shipping_method'] == '顺丰标快'


def test_estimate_sf_logistics_uses_default_for_unknown_location():
    result = estimate_sf_logistics('测试收件人 13800138000 海外地址')

    assert result['logistics_days'] == 3
    assert result['matched_location'] is None
    assert '默认 3 天' in result['message']


@pytest.mark.parametrize('destination', ['', '   ', None])
def test_estimate_sf_logistics_rejects_empty_destination(destination):
    with pytest.raises(ValueError, match='目的地地址不能为空'):
        estimate_sf_logistics(destination)

