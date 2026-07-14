"""物流时效预估 API 测试。"""

import importlib.util
from pathlib import Path

import pytest
from flask import Flask


def _load_rental_api_blueprint():
    """绕过 routes 包的全量导入，只加载本测试需要的租赁路由。"""
    route_path = Path(__file__).parents[2] / 'app' / 'routes' / 'rental_api.py'
    spec = importlib.util.spec_from_file_location('isolated_rental_api', route_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bp


rental_api_bp = _load_rental_api_blueprint()


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(rental_api_bp)
    return app.test_client()


def test_estimate_logistics_api_returns_estimate(client):
    response = client.get(
        '/api/rentals/estimate-logistics',
        query_string={'destination': '江苏省南京市鼓楼区'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert payload['data']['logistics_days'] == 2
    assert payload['data']['matched_location'] == '江苏'


def test_estimate_logistics_api_rejects_empty_destination(client):
    response = client.get('/api/rentals/estimate-logistics')

    assert response.status_code == 400
    payload = response.get_json()
    assert payload == {
        'success': False,
        'message': '目的地地址不能为空',
    }
