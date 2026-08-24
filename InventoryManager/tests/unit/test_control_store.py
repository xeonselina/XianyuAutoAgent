import base64
from datetime import datetime, timedelta

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import func, select

from app import create_app
from app.control.models import ControlBase, Tenant
from app.control.store import ControlStore
from app.crypto import SecretBox, digest_sms_code, hash_token
from config import Config, ProductionConfig, TestingConfig


@pytest.fixture
def master_key():
    return base64.b64encode(bytes(range(32))).decode("ascii")


def test_secret_box_binds_ciphertext_to_purpose(master_key):
    box = SecretBox.from_base64(master_key)

    encrypted = box.encrypt("secret", purpose="tenant-db-password")

    assert box.decrypt(encrypted, purpose="tenant-db-password") == "secret"
    with pytest.raises(InvalidTag):
        box.decrypt(encrypted, purpose="sf-checkword")


def test_secret_box_rejects_wrong_master_key(master_key):
    encrypted = SecretBox.from_base64(master_key).encrypt(
        "secret", purpose="tenant-db-password"
    )
    other_key = base64.b64encode(bytes(reversed(range(32)))).decode("ascii")

    with pytest.raises(InvalidTag):
        SecretBox.from_base64(other_key).decrypt(
            encrypted, purpose="tenant-db-password"
        )


@pytest.mark.parametrize(
    "encoded_key",
    [
        "not-base64!",
        base64.b64encode(b"too-short").decode("ascii"),
    ],
)
def test_secret_box_requires_base64_encoded_32_byte_key(encoded_key):
    with pytest.raises(ValueError):
        SecretBox.from_base64(encoded_key)


def test_token_and_sms_code_are_one_way_digests():
    assert hash_token("raw-token-value") == (
        "43a2860580227e27192a056eec8cceabf9c499d5c20c755f4b75434330253de4"
    )
    assert digest_sms_code(
        "+8613800138000", "123456", bytes(range(32))
    ) == "9d4bb6fd49baeb40204fd4d5307f7c9c8300ea3f37b89b9eb40667897fb1befb"


def test_control_models_have_no_raw_token_or_sms_code_columns():
    auth_columns = set(
        ControlBase.metadata.tables["auth_sessions"].columns.keys()
    )
    sms_columns = set(
        ControlBase.metadata.tables["sms_login_codes"].columns.keys()
    )

    assert "token" not in auth_columns
    assert "token_hash" in auth_columns
    assert "code" not in sms_columns
    assert "code_digest" in sms_columns


def test_control_store_commits_and_rolls_back_short_sessions(
    tmp_path, master_key
):
    box = SecretBox.from_base64(master_key)
    store = ControlStore(
        f"sqlite+pysqlite:///{tmp_path / 'control.db'}",
        secret_box=box,
    )
    ControlBase.metadata.create_all(store.engine)
    expires_at = datetime.utcnow() + timedelta(days=30)

    with store.session() as session:
        session.add(
            Tenant(
                name="租户 A",
                status="active",
                expires_at=expires_at,
                db_name="tenant_a",
                db_username="tenant_a_user",
                db_password_ciphertext=box.encrypt(
                    "password-a", purpose="tenant-db-password"
                ),
                provisioning_status="active",
            )
        )

    assert not session.in_transaction()
    assert not session.identity_map

    with pytest.raises(RuntimeError, match="abort transaction"):
        with store.session() as session:
            session.add(
                Tenant(
                    name="租户 B",
                    status="active",
                    expires_at=expires_at,
                    db_name="tenant_b",
                    db_username="tenant_b_user",
                    db_password_ciphertext=box.encrypt(
                        "password-b", purpose="tenant-db-password"
                    ),
                    provisioning_status="active",
                )
            )
            raise RuntimeError("abort transaction")

    with store.session() as session:
        tenant_count = session.scalar(select(func.count()).select_from(Tenant))

    assert tenant_count == 1
    store.dispose()


def test_production_startup_rejects_missing_master_key():
    class MissingKeyProductionConfig(ProductionConfig):
        SAAS_MASTER_KEY = None
        DEV_SMS_CODE = None

    with pytest.raises(RuntimeError, match="SAAS_MASTER_KEY"):
        create_app(MissingKeyProductionConfig)


def test_production_startup_rejects_default_development_master_key():
    class DefaultKeyProductionConfig(ProductionConfig):
        SAAS_MASTER_KEY = Config.DEFAULT_SAAS_MASTER_KEY
        DEV_SMS_CODE = None

    with pytest.raises(RuntimeError, match="SAAS_MASTER_KEY"):
        create_app(DefaultKeyProductionConfig)


def test_production_startup_rejects_development_sms_code(master_key):
    class DevSmsProductionConfig(ProductionConfig):
        SAAS_MASTER_KEY = master_key
        DEV_SMS_CODE = "123456"

    with pytest.raises(RuntimeError, match="DEV_SMS_CODE"):
        create_app(DevSmsProductionConfig)


def test_testing_startup_allows_development_security_defaults():
    application = create_app(TestingConfig)

    assert application.testing is True
