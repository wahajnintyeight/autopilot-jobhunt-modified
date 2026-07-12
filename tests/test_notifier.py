"""Telegram/WhatsApp senders — HTTP is mocked; assert graceful success/failure paths."""

from job_hunt import notifier


class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_send_telegram_success(monkeypatch, capsys):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        return _Resp(200)

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    assert notifier.send_telegram("tok", "chat", "hi") is True
    assert "bottok/sendMessage" in seen["url"]
    assert seen["json"]["parse_mode"] == "HTML"
    assert "Telegram sent." in capsys.readouterr().out


def test_send_telegram_http_error(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: _Resp(400, "bad"))
    assert notifier.send_telegram("tok", "chat", "hi") is False


def test_send_telegram_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(notifier.requests, "post", boom)
    assert notifier.send_telegram("tok", "chat", "hi") is False


def test_send_whatsapp_success(monkeypatch):
    monkeypatch.setattr(notifier.requests, "get", lambda *a, **k: _Resp(200))
    assert notifier.send_whatsapp("123", "key", "hi there") is True


def test_send_whatsapp_http_error(monkeypatch):
    monkeypatch.setattr(notifier.requests, "get", lambda *a, **k: _Resp(500, "err"))
    assert notifier.send_whatsapp("123", "key", "hi") is False


def test_send_whatsapp_exception(monkeypatch):
    monkeypatch.setattr(notifier.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert notifier.send_whatsapp("123", "key", "hi") is False


def test_send_discord_success(monkeypatch, capsys):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        return _Resp(204)

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    assert notifier.send_discord("https://discord.com/api/webhooks/abc", "hi") is True
    assert seen["url"] == "https://discord.com/api/webhooks/abc"
    assert seen["json"]["content"] == "@everyone\nhi"
    assert seen["json"]["allowed_mentions"]["parse"] == ["everyone"]
    assert "Discord sent." in capsys.readouterr().out


def test_send_discord_splits_long_messages(monkeypatch):
    payloads = []

    def fake_post(url, json=None, timeout=None):
        payloads.append(json)
        return _Resp(204)

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    assert notifier.send_discord("https://discord.com/api/webhooks/abc", "x" * 2500) is True
    assert len(payloads) == 2
    assert all(len(payload["content"]) <= 2000 for payload in payloads)
    assert all(payload["content"].startswith("@everyone\n") for payload in payloads)


def test_send_discord_http_error(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: _Resp(400, "bad"))
    assert notifier.send_discord("https://discord.com/api/webhooks/abc", "hi") is False


def test_send_discord_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(notifier.requests, "post", boom)
    assert notifier.send_discord("https://discord.com/api/webhooks/abc", "hi") is False
