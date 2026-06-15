"""Tests for Telegram Mini App initData validation."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode


def _signed_init_data(bot_token: str, *, user_id: int = 123, auth_date: int | None = None) -> str:
    payload = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "first_name": "Ada"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(payload)


def test_validate_telegram_init_data_accepts_signed_payload():
    from bot.miniapp_api import validate_telegram_init_data

    auth = validate_telegram_init_data(
        _signed_init_data("bot-token", user_id=777),
        bot_token="bot-token",
        max_age_seconds=3600,
    )

    assert auth.user_id == 777
    assert auth.user["first_name"] == "Ada"


def test_validate_telegram_init_data_rejects_tampered_hash():
    from bot.miniapp_api import InitDataAuthError, validate_telegram_init_data

    init_data = _signed_init_data("bot-token", user_id=777).replace("777", "778")

    try:
        validate_telegram_init_data(init_data, bot_token="bot-token", max_age_seconds=3600)
    except InitDataAuthError as exc:
        assert str(exc) == "invalid_hash"
    else:
        raise AssertionError("tampered initData was accepted")


def test_validate_telegram_init_data_rejects_expired_payload():
    from bot.miniapp_api import InitDataAuthError, validate_telegram_init_data

    init_data = _signed_init_data("bot-token", auth_date=int(time.time()) - 7200)

    try:
        validate_telegram_init_data(init_data, bot_token="bot-token", max_age_seconds=60)
    except InitDataAuthError as exc:
        assert str(exc) == "expired_init_data"
    else:
        raise AssertionError("expired initData was accepted")
