"""闲鱼漏录订单对账服务测试。"""

import pytest


@pytest.fixture
def app():
    from app import create_app

    return create_app("testing")


@pytest.fixture
def db_session(app):
    from app import db

    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


def test_alert_serializes_amount_and_order_fields(app, db_session):
    from app.models.xianyu_order_alert import XianyuOrderAlert

    with app.app_context():
        alert = XianyuOrderAlert(
            order_no=" XY-1 ",
            state="pending",
            pay_amount=5001,
            buyer_nick="买家",
            receiver_mobile="13800138000",
            goods_title="相机租赁",
        )
        db_session.add(alert)
        db_session.commit()

        payload = alert.to_dict()

        assert alert.order_no == "XY-1"
        assert payload["pay_amount"] == 5001
        assert payload["buyer_nick"] == "买家"
