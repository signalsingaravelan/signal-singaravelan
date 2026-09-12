"""Tests for AWS Secrets Manager loading (algo_trader.utils.secrets)."""

import json

import pytest
from botocore.exceptions import ClientError

from algo_trader.utils import secrets as secrets_module
from algo_trader.utils.secrets import (
    clear_secrets_cache,
    get_secret_value,
    get_secrets,
    load_secrets,
)


SAMPLE_SECRETS = {
    "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
    "MASSIVE_API_KEY": "massive-key",
    "ALPACA_API_KEY_TAXABLE": "key123",
    "ALPACA_API_SECRET_TAXABLE": "secret123",
}


@pytest.fixture(autouse=True)
def _reset_secrets_state(monkeypatch):
    clear_secrets_cache()
    for key in list(SAMPLE_SECRETS):
        monkeypatch.delenv(key, raising=False)
    yield
    clear_secrets_cache()


def _mock_secrets_client(monkeypatch, secret_payload):
    calls = {"count": 0}

    class FakeClient:
        def get_secret_value(self, SecretId):
            calls["count"] += 1
            if isinstance(secret_payload, Exception):
                raise secret_payload
            return {"SecretString": secret_payload}

    monkeypatch.setattr(
        secrets_module.boto3,
        "client",
        lambda *args, **kwargs: FakeClient(),
    )
    return calls


def test_load_secrets_hydrates_alpaca_env_only(monkeypatch):
    calls = _mock_secrets_client(monkeypatch, json.dumps(SAMPLE_SECRETS))

    result = load_secrets()

    assert result == SAMPLE_SECRETS
    assert calls["count"] == 1
    assert secrets_module.os.environ["ALPACA_API_KEY_TAXABLE"] == "key123"
    assert secrets_module.os.environ["ALPACA_API_SECRET_TAXABLE"] == "secret123"
    assert "MASSIVE_API_KEY" not in secrets_module.os.environ
    assert get_secret_value("MASSIVE_API_KEY") == "massive-key"
    assert get_secret_value("TELEGRAM_BOT_TOKEN") == "123456:ABC-DEF"


def test_get_secrets_uses_cache_on_second_call(monkeypatch):
    calls = _mock_secrets_client(monkeypatch, json.dumps(SAMPLE_SECRETS))

    first = get_secrets()
    second = get_secrets()

    assert first is second
    assert calls["count"] == 1


def test_invalid_json_raises(monkeypatch):
    _mock_secrets_client(monkeypatch, "{not-json")

    with pytest.raises(RuntimeError, match="not valid JSON"):
        get_secrets()


def test_secrets_manager_client_error_raises(monkeypatch):
    error = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "not found"}},
        "GetSecretValue",
    )
    _mock_secrets_client(monkeypatch, error)

    with pytest.raises(RuntimeError, match="Failed to retrieve secret"):
        get_secrets()


def test_get_secret_value_returns_none_for_missing_key(monkeypatch):
    _mock_secrets_client(monkeypatch, json.dumps(SAMPLE_SECRETS))

    assert get_secret_value("MISSING_KEY") is None
