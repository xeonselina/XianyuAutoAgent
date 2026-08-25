from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_restore_scripts_require_an_explicit_database_password():
    python_source = (ROOT / "scripts/restore.py").read_text()
    shell_source = (ROOT / "scripts/restore.sh").read_text()

    assert "DEFAULT_PASS" not in python_source
    assert 'os.environ.get("MYSQL_PASSWORD")' in python_source
    assert "if not password:" in python_source
    assert 'DB_PASSWORD="${MYSQL_PASSWORD:-}"' in shell_source
    assert 'if [[ -z "$DB_PASSWORD" ]]' in shell_source
    assert shell_source.index("set +x") < shell_source.index("DB_PASSWORD=")


def test_nas_deploy_requires_explicit_passwords_without_xtrace():
    source = (ROOT / "scripts/deploy_nas.sh").read_text()
    make_source = (ROOT / "Makefile").read_text()

    assert 'NAS_PASS="${NAS_PASS:-}"' in source
    assert 'SUDO_PASS="${SUDO_PASS:-$NAS_PASS}"' in source
    assert 'if [[ -z "$NAS_PASS" || -z "$SUDO_PASS" ]]' in source
    assert source.index("set +x") < source.index("NAS_PASS=")
    assert "***REMOVED***" not in source
    assert "NAS_PASS     ?=" in make_source
    assert make_source.count('if [ -z "$(NAS_PASS)" ]') >= 2
    assert "***REMOVED***" not in make_source


def test_customer_guidance_uses_safe_runtime_address_prompt():
    tool_source = (ROOT / "tools/get_return_address.py").read_text()
    knowledge_source = (ROOT / "scripts/init_rental_knowledge.py").read_text()

    assert "***REMOVED" not in tool_source + knowledge_source
    assert "请联系客服获取最新归还地址" in tool_source
    assert "以客服实时提供的地址为准" in knowledge_source
