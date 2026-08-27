from __future__ import annotations

import app as app_pkg
from app import create_app
from app.config import TestingConfig
from app.services import alerts


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


def _disable_runtime_initializers(monkeypatch):
    monkeypatch.setattr(app_pkg, "init_extensions", lambda app: None)
    monkeypatch.setattr(app_pkg, "register_operations_cli", lambda app: None)
    monkeypatch.setattr(app_pkg, "init_auth", lambda app: None)
    monkeypatch.setattr(app_pkg, "register_blueprints", lambda app: None)
    monkeypatch.setattr(app_pkg, "register_error_handlers", lambda app: None)
    monkeypatch.setattr(app_pkg, "register_before_request", lambda app: None)


def test_teams_alert_posts_safe_payload_when_enabled():
    calls = []

    def fake_post(url, *, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(202, "accepted")

    config = {
        "APP_ENV": "production",
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "https://teams.example/webhook",
        "TEAMS_ALERT_TIMEOUT_SECONDS": 2.5,
        "TEAMS_ALERT_DEDUP_SECONDS": 900,
        "TEAMS_ALERT_HOST": "translate-prod-01",
    }

    result = alerts.send_teams_alert(
        config,
        source="ocr.pipeline",
        message="OCR API 請求連續失敗 3 次",
        exception_type="RuntimeError",
        job_id="abc123",
        detail={
            "stage": "ocr",
            "job_type": "ocr_overlay",
            "path": "/api/job/abc123?token=secret",
            "method": "POST",
            "endpoint": "api.batch_translate",
            "worker_id": "worker-1",
            "traceback": "secret stack",
            "query_string": "token=secret",
            "exception_message": "internal secret",
        },
        post=fake_post,
        now=lambda: 1000.0,
    )

    assert result.sent is True
    assert result.status_code == 202
    assert calls == [
        {
            "url": "https://teams.example/webhook",
            "timeout": 2.5,
            "json": {
                "status": "ERROR",
                "service": "pdf-ocr-translate",
                "host": "translate-prod-01",
                "time": "1970-01-01 08:16:40",
                "message": "OCR API 請求連續失敗 3 次",
                "source": "ocr.pipeline",
                "environment": "production",
                "job_id": "abc123",
                "job_type": "ocr_overlay",
                "stage": "ocr",
                "exception_type": "RuntimeError",
                "path": "/api/job/abc123",
                "method": "POST",
                "endpoint": "api.batch_translate",
                "worker_id": "worker-1",
            },
        }
    ]


def test_teams_alert_is_disabled_without_webhook_url():
    calls = []
    config = {
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "",
    }

    result = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        post=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert result.sent is False
    assert result.reason == "disabled"
    assert calls == []


def test_teams_alert_deduplicates_repeated_alerts():
    calls = []
    config = {
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "https://teams.example/webhook",
        "TEAMS_ALERT_DEDUP_SECONDS": 900,
    }
    cache = alerts.AlertDedupCache()

    first = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        exception_type="RuntimeError",
        job_id="job-1",
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse(),
        dedup_cache=cache,
        now=lambda: 1000.0,
    )
    second = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        exception_type="RuntimeError",
        job_id="job-1",
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse(),
        dedup_cache=cache,
        now=lambda: 1100.0,
    )

    assert first.sent is True
    assert second.sent is False
    assert second.reason == "deduplicated"
    assert len(calls) == 1


def test_teams_alert_dedup_ttl_zero_disables_deduplication():
    calls = []
    config = {
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "https://teams.example/webhook",
        "TEAMS_ALERT_DEDUP_SECONDS": 0,
    }
    cache = alerts.AlertDedupCache()

    first = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse(),
        dedup_cache=cache,
        now=lambda: 1000.0,
    )
    second = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse(),
        dedup_cache=cache,
        now=lambda: 1000.05,
    )

    assert first.sent is True
    assert second.sent is True
    assert len(calls) == 2


def test_teams_alert_allows_same_alert_after_dedup_ttl_expires():
    calls = []
    config = {
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "https://teams.example/webhook",
        "TEAMS_ALERT_DEDUP_SECONDS": 10,
    }
    cache = alerts.AlertDedupCache()

    first = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        exception_type="RuntimeError",
        job_id="job-1",
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse(),
        dedup_cache=cache,
        now=lambda: 1000.0,
    )
    second = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        exception_type="RuntimeError",
        job_id="job-1",
        post=lambda *args, **kwargs: calls.append((args, kwargs)) or FakeResponse(),
        dedup_cache=cache,
        now=lambda: 1011.0,
    )

    assert first.sent is True
    assert second.sent is True
    assert len(calls) == 2


def test_teams_alert_logs_warning_and_does_not_raise_on_delivery_failure(monkeypatch):
    warnings = []
    config = {
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "https://teams.example/webhook",
    }

    def fail_post(*args, **kwargs):
        raise TimeoutError("network slow")

    monkeypatch.setattr(alerts.logger, "warning", lambda message, *args: warnings.append((message, args)))

    result = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        post=fail_post,
        dedup_cache=alerts.AlertDedupCache(),
    )

    assert result.sent is False
    assert result.reason == "delivery_failed"
    assert warnings[0][0] == "Teams Alert delivery failed error=%s"


def test_teams_alert_logs_warning_and_does_not_raise_on_non_2xx(monkeypatch):
    warnings = []
    config = {
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "https://teams.example/webhook",
    }

    monkeypatch.setattr(alerts.logger, "warning", lambda message, *args: warnings.append((message, args)))

    result = alerts.send_teams_alert(
        config,
        source="worker.loop",
        message="Worker loop failure",
        post=lambda *args, **kwargs: FakeResponse(500, "server error"),
        dedup_cache=alerts.AlertDedupCache(),
    )

    assert result.sent is False
    assert result.reason == "delivery_failed"
    assert result.status_code == 500
    assert warnings[0][0] == "Teams Alert delivery failed status_code=%s response=%s"
    assert warnings[0][1] == (500, "server error")


def test_startup_warns_when_teams_alert_enabled_without_webhook(monkeypatch):
    warnings = []
    _disable_runtime_initializers(monkeypatch)
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_WEBHOOK_URL", "")
    monkeypatch.setattr(
        alerts.logger, "warning", lambda message, *args: warnings.append((message, args))
    )

    app = create_app("testing")

    assert app.config["TEAMS_ALERT_ENABLED"] is True
    assert warnings[0][0].startswith(
        "Teams Alert is enabled but TEAMS_ALERT_WEBHOOK_URL is empty"
    )


def test_alerts_test_teams_cli_sends_test_alert_and_bypasses_dedup(monkeypatch):
    calls = []
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_ENABLED", True)
    monkeypatch.setattr(
        TestingConfig, "TEAMS_ALERT_WEBHOOK_URL", "https://teams.example/webhook"
    )
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_DEDUP_SECONDS", 900.0)
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_HOST", "test-host")

    def fake_post(url, *, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(204, "")

    monkeypatch.setattr(alerts.requests, "post", fake_post)
    app = create_app("testing")
    runner = app.test_cli_runner()

    first = runner.invoke(args=["alerts", "test-teams"])
    second = runner.invoke(args=["alerts", "test-teams"])

    assert first.exit_code == 0
    assert "teams_alert_test ok=1 status_code=204" in first.output
    assert second.exit_code == 0
    assert len(calls) == 2
    assert calls[0]["json"]["source"] == "alerts.test"
    assert calls[0]["json"]["message"] == "Teams Alert test"
    assert calls[0]["json"]["host"] == "test-host"


def test_alerts_test_teams_cli_fails_when_webhook_missing(monkeypatch):
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_WEBHOOK_URL", "")

    app = create_app("testing")
    result = app.test_cli_runner().invoke(args=["alerts", "test-teams"])

    assert result.exit_code != 0
    assert "Teams Alert is disabled or TEAMS_ALERT_WEBHOOK_URL is empty" in result.output


def test_alerts_test_teams_cli_fails_on_rejected_webhook(monkeypatch):
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_ENABLED", True)
    monkeypatch.setattr(
        TestingConfig, "TEAMS_ALERT_WEBHOOK_URL", "https://teams.example/webhook"
    )
    monkeypatch.setattr(
        alerts.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(500, "server error"),
    )

    app = create_app("testing")
    result = app.test_cli_runner().invoke(args=["alerts", "test-teams"])

    assert result.exit_code != 0
    assert "Teams Alert test failed reason=delivery_failed" in result.output
    assert "status_code=500" in result.output
    assert "response=server error" in result.output


def test_alerts_test_teams_cli_fails_on_timeout(monkeypatch):
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_ENABLED", True)
    monkeypatch.setattr(
        TestingConfig, "TEAMS_ALERT_WEBHOOK_URL", "https://teams.example/webhook"
    )

    def fail_post(*args, **kwargs):
        raise alerts.requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(alerts.requests, "post", fail_post)

    app = create_app("testing")
    result = app.test_cli_runner().invoke(args=["alerts", "test-teams"])

    assert result.exit_code != 0
    assert "Teams Alert test failed reason=timeout" in result.output
    assert "response=Timeout: timed out" in result.output


def test_alerts_test_teams_cli_fails_on_request_failure(monkeypatch):
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_ENABLED", True)
    monkeypatch.setattr(
        TestingConfig, "TEAMS_ALERT_WEBHOOK_URL", "https://teams.example/webhook"
    )

    def fail_post(*args, **kwargs):
        raise alerts.requests.exceptions.RequestException("connection failed")

    monkeypatch.setattr(alerts.requests, "post", fail_post)

    app = create_app("testing")
    result = app.test_cli_runner().invoke(args=["alerts", "test-teams"])

    assert result.exit_code != 0
    assert "Teams Alert test failed reason=request_failed" in result.output
    assert "response=RequestException: connection failed" in result.output
