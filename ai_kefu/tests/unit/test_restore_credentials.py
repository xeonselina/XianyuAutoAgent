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

    assert 'NAS_PASS="${NAS_PASS:-}"' in source
    assert 'SUDO_PASS="${SUDO_PASS:-$NAS_PASS}"' in source
    assert 'if [[ -z "$NAS_PASS" || -z "$SUDO_PASS" ]]' in source
    assert source.index("set +x") < source.index("NAS_PASS=")
    assert "***REMOVED***" not in source
