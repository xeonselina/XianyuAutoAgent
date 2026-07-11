import os

from sqlalchemy.engine import make_url

from config import TestingConfig


def assert_test_database_url(url: str):
    """拒绝测试进程使用生产业务库。"""
    if os.environ.get("TESTING", "").lower() != "true":
        raise RuntimeError("必须设置 TESTING=true")

    parsed = make_url(url)
    if "test" not in (parsed.database or "").lower():
        raise RuntimeError("测试数据库名必须包含 test")
    return parsed


def assert_current_user_has_test_only_grants(connection, database_name: str):
    """确认 MySQL 当前账号没有测试库以外的数据权限。"""
    grants = [
        row[0]
        for row in connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER").all()
    ]
    allowed_global_prefix = "GRANT USAGE ON *.*"
    allowed_database_tokens = {
        f"ON `{database_name}`.*",
        f"ON {database_name}.*",
    }

    for grant in grants:
        normalized_grant = grant.replace("\\_", "_").replace("\\%", "%")
        if normalized_grant.startswith(allowed_global_prefix):
            continue
        if not any(
            token in normalized_grant for token in allowed_database_tokens
        ):
            raise RuntimeError("测试数据库账号拥有测试库以外的权限")


def build_mysql_test_config():
    """从显式 TEST_DATABASE_URL 构建隔离 MySQL 测试配置。"""
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("缺少 TEST_DATABASE_URL")
    parsed = assert_test_database_url(raw_url)

    class MySQLTestingConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = parsed.render_as_string(
            hide_password=False
        )
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    return MySQLTestingConfig
