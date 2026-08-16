"""Tests for accounts.yaml loading/validation (algo_trader.config.account_config)."""

import pytest

from algo_trader.config.account_config import load_accounts, get_enabled_accounts


VALID_YAML = """
accounts:
  - name: taxable
    enabled: true
    paper: true
    api_key_env: ALPACA_API_KEY_TAXABLE
    api_secret_env: ALPACA_API_SECRET_TAXABLE
    allocations:
      TQQQ: 100
  - name: roth-ira
    enabled: false
    paper: true
    api_key_env: ALPACA_API_KEY_ROTH_IRA
    api_secret_env: ALPACA_API_SECRET_ROTH_IRA
    allocations:
      VTI: 20
      VOO: 20
      VUG: 30
      VGT: 15
      QQQ: 15
"""


def _write(tmp_path, contents):
    path = tmp_path / "accounts.yaml"
    path.write_text(contents)
    return str(path)


def test_load_accounts_parses_valid_config(tmp_path):
    accounts = load_accounts(_write(tmp_path, VALID_YAML))
    assert [a.name for a in accounts] == ["taxable", "roth-ira"]
    assert accounts[0].allocations == {"TQQQ": 100}


def test_get_enabled_accounts_filters_disabled(tmp_path):
    enabled = get_enabled_accounts(_write(tmp_path, VALID_YAML))
    assert [a.name for a in enabled] == ["taxable"]


def test_allocations_not_summing_to_100_raises(tmp_path):
    bad_yaml = """
accounts:
  - name: taxable
    enabled: true
    paper: true
    api_key_env: ALPACA_API_KEY_TAXABLE
    api_secret_env: ALPACA_API_SECRET_TAXABLE
    allocations:
      TQQQ: 90
"""
    with pytest.raises(ValueError, match="100%"):
        load_accounts(_write(tmp_path, bad_yaml))


def test_disabled_account_with_bad_allocations_does_not_raise(tmp_path):
    yaml_content = """
accounts:
  - name: taxable
    enabled: false
    paper: true
    api_key_env: ALPACA_API_KEY_TAXABLE
    api_secret_env: ALPACA_API_SECRET_TAXABLE
    allocations:
      TQQQ: 50
"""
    accounts = load_accounts(_write(tmp_path, yaml_content))
    assert accounts[0].enabled is False


def test_duplicate_account_names_raise(tmp_path):
    dup_yaml = """
accounts:
  - name: taxable
    enabled: true
    paper: true
    api_key_env: A
    api_secret_env: B
    allocations:
      TQQQ: 100
  - name: taxable
    enabled: true
    paper: true
    api_key_env: C
    api_secret_env: D
    allocations:
      QQQ: 100
"""
    with pytest.raises(ValueError, match="Duplicate account name"):
        load_accounts(_write(tmp_path, dup_yaml))


def test_missing_credential_env_vars_raises_on_resolve(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_TAXABLE", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_TAXABLE", raising=False)

    accounts = load_accounts(_write(tmp_path, VALID_YAML))
    with pytest.raises(ValueError, match="Missing Alpaca credentials"):
        accounts[0].resolve_credentials()


def test_resolve_credentials_reads_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_TAXABLE", "key123")
    monkeypatch.setenv("ALPACA_API_SECRET_TAXABLE", "secret123")

    accounts = load_accounts(_write(tmp_path, VALID_YAML))
    api_key, api_secret = accounts[0].resolve_credentials()
    assert (api_key, api_secret) == ("key123", "secret123")


def test_no_accounts_defined_raises(tmp_path):
    with pytest.raises(ValueError, match="No accounts defined"):
        load_accounts(_write(tmp_path, "accounts: []"))
