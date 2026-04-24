"""Tests for check_gmail_watch_health (per-account version).

Covers the post-Apr-24-2026 rewrite: per-account staleness via direct pg
query, schedule existence probe with retry, top-level error envelope, and
SMS delivery status tracking.

Mocks are unavoidable: wmill SDK is only available inside Windmill's
sandbox, psycopg2 requires a live DB, and requests make real HTTP calls.
"""

import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

# Create a fake wmill module so the script can be imported outside Windmill
_wmill_mock = types.ModuleType("wmill")
_wmill_mock.get_variable = MagicMock()
_wmill_mock.get_resource = MagicMock()
sys.modules["wmill"] = _wmill_mock

# Create a fake psycopg2 module — we patch psycopg2.connect in individual tests
_psycopg2_mock = types.ModuleType("psycopg2")
_psycopg2_mock.connect = MagicMock()
sys.modules["psycopg2"] = _psycopg2_mock

from f.switchboard.check_gmail_watch_health import (  # noqa: E402
    main,
    run_checks,
    check_account_staleness,
    check_schedules_enabled,
    attempt_self_heal,
    try_send_alert,
    send_alert,
    format_alert,
    WATCH_SCRIPTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOKEN = "test-token-123"
SMS_URL = "http://100.125.176.16:8686/send-sms"
PG_RESOURCE = {
    "host": "localhost",
    "port": 5432,
    "dbname": "windmill",
    "user": "postgres",
    "password": "pw",
    "sslmode": "disable",
}


def _setup_wmill_vars(vars_dict=None):
    """Configure wmill.get_variable to return expected values."""
    defaults = {
        "f/switchboard/router_token": TOKEN,
        "f/switchboard/sms_gateway_url": SMS_URL,
    }
    if vars_dict is not None:
        defaults.update(vars_dict)
    _wmill_mock.get_variable = MagicMock(side_effect=lambda name: defaults[name])
    _wmill_mock.get_resource = MagicMock(return_value=PG_RESOURCE)


def _fake_conn(staleness_by_account):
    """Build a fake psycopg2 connection whose cursor returns a row for each
    account_key in staleness_by_account (maps account_key -> hours_ago or None).
    """
    def cursor_factory():
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        # The script calls cur.execute(sql, (account_key,)) then cur.fetchone()
        # We track the last-executed account_key to decide the return row.
        state = {"last_account": None}

        def execute(sql, params):
            state["last_account"] = params[0]
        cur.execute = execute

        def fetchone():
            acct = state["last_account"]
            hours = staleness_by_account.get(acct)
            if hours is None:
                return None
            ts = datetime.now(timezone.utc) - timedelta(hours=hours)
            return (ts,)
        cur.fetchone = fetchone
        return cur

    conn = MagicMock()
    conn.cursor = cursor_factory
    conn.close = MagicMock()
    return conn


def _schedule_response(enabled=True, status=200, body=None):
    resp = MagicMock()
    resp.status_code = status
    if status == 404:
        resp.raise_for_status = MagicMock()
    elif status >= 400:
        resp.raise_for_status = MagicMock(side_effect=Exception(f"HTTP {status}"))
    else:
        resp.raise_for_status = MagicMock()
    resp.json.return_value = body if body is not None else {"enabled": enabled}
    return resp


def _renewal_success():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '"job-id-abc"'
    return resp


def _sms_response(ok=True):
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = 200 if ok else 502
    resp.text = "ok" if ok else "gateway down"
    return resp


# ---------------------------------------------------------------------------
# Happy path: both accounts fresh, both schedules enabled
# ---------------------------------------------------------------------------

class TestHealthy:
    @patch("f.switchboard.check_gmail_watch_health.psycopg2")
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_healthy_returns_per_account_status(self, mock_requests, mock_psycopg2):
        _setup_wmill_vars()
        # Both schedules enabled
        mock_requests.get.return_value = _schedule_response(enabled=True)
        # Both accounts fresh (5 hours ago)
        mock_psycopg2.connect.return_value = _fake_conn({"leads": 5, "teamgotcher": 5})

        result = main()

        assert result["status"] == "healthy"
        assert result["accounts"]["leads"]["label"] == "leads@"
        assert result["accounts"]["teamgotcher"]["label"] == "teamgotcher@"
        assert 4 < result["accounts"]["leads"]["hours_since"] < 6
        # No SMS and no renewal submissions
        mock_requests.post.assert_not_called()


# ---------------------------------------------------------------------------
# Per-account staleness: one account silent, other fresh
# ---------------------------------------------------------------------------

class TestPerAccountStaleness:
    @patch("f.switchboard.check_gmail_watch_health.psycopg2")
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_leads_stale_teamgotcher_fresh_triggers_alert(self, mock_requests, mock_psycopg2):
        """The April 16 outage scenario — leads@ silent, teamgotcher@ busy.
        Previously this reported healthy globally; now it must flag leads@."""
        _setup_wmill_vars()
        mock_requests.get.return_value = _schedule_response(enabled=True)
        mock_psycopg2.connect.return_value = _fake_conn({"leads": 200, "teamgotcher": 0.1})
        # POST mock — renewals + SMS all succeed
        mock_requests.post.side_effect = lambda url, **kw: (
            _sms_response(ok=True) if SMS_URL in url else _renewal_success()
        )

        result = main()

        assert result["status"] == "alert_sent"
        assert result["alert_delivered"] is True
        assert any("leads@" in i and "stale" in i for i in result["issues"])
        assert not any("teamgotcher@" in i and "stale" in i for i in result["issues"])
        # Two renewals queued + one SMS call
        sms_calls = [c for c in mock_requests.post.call_args_list if SMS_URL in str(c)]
        assert len(sms_calls) == 1

    @patch("f.switchboard.check_gmail_watch_health.psycopg2")
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_no_jobs_for_an_account_is_flagged(self, mock_requests, mock_psycopg2):
        _setup_wmill_vars()
        mock_requests.get.return_value = _schedule_response(enabled=True)
        # leads: no jobs found; teamgotcher: fresh
        mock_psycopg2.connect.return_value = _fake_conn({"leads": None, "teamgotcher": 0.5})
        mock_requests.post.side_effect = lambda url, **kw: (
            _sms_response(ok=True) if SMS_URL in url else _renewal_success()
        )

        result = main()

        assert result["status"] == "alert_sent"
        assert any("leads@" in i and "no prior webhook jobs" in i for i in result["issues"])


# ---------------------------------------------------------------------------
# Schedule existence probe
# ---------------------------------------------------------------------------

class TestScheduleProbe:
    @patch("f.switchboard.check_gmail_watch_health.psycopg2")
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_missing_schedule_flagged(self, mock_requests, mock_psycopg2):
        """404 on a schedule probe appends it to issues and triggers alert."""
        _setup_wmill_vars()
        mock_psycopg2.connect.return_value = _fake_conn({"leads": 1, "teamgotcher": 1})

        def route_get(url, **kw):
            if "schedule_gmail_leads_watch_renewal" in url:
                return _schedule_response(status=404, body={})
            return _schedule_response(enabled=True)

        mock_requests.get.side_effect = route_get
        mock_requests.post.side_effect = lambda url, **kw: (
            _sms_response(ok=True) if SMS_URL in url else _renewal_success()
        )

        result = main()

        assert result["status"] == "alert_sent"
        assert any("schedule" in i and "missing or disabled" in i for i in result["issues"])

    @patch("f.switchboard.check_gmail_watch_health.psycopg2")
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_disabled_schedule_flagged(self, mock_requests, mock_psycopg2):
        _setup_wmill_vars()
        mock_psycopg2.connect.return_value = _fake_conn({"leads": 1, "teamgotcher": 1})

        def route_get(url, **kw):
            if "schedule_gmail_leads_watch_renewal" in url:
                return _schedule_response(enabled=False)
            return _schedule_response(enabled=True)

        mock_requests.get.side_effect = route_get
        mock_requests.post.side_effect = lambda url, **kw: (
            _sms_response(ok=True) if SMS_URL in url else _renewal_success()
        )

        result = main()

        assert result["status"] == "alert_sent"
        assert any("missing or disabled" in i for i in result["issues"])


# ---------------------------------------------------------------------------
# Retry behavior in check_schedules_enabled
# ---------------------------------------------------------------------------

class TestScheduleProbeRetry:
    @patch("f.switchboard.check_gmail_watch_health.time.sleep", return_value=None)
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_transient_error_retried_then_succeeds(self, mock_requests, _sleep):
        """First call throws, second returns enabled=True. No issue appended."""
        call_state = {"count": 0}

        def flaky_get(url, **kw):
            call_state["count"] += 1
            if call_state["count"] == 1:
                raise Exception("transient ECONNREFUSED")
            return _schedule_response(enabled=True)

        mock_requests.get.side_effect = flaky_get
        problems = check_schedules_enabled(TOKEN)
        assert problems == []
        # Both schedules tried; first retries once (2 calls) + second succeeds (1 call) = 3 total
        # But the loop iterates once per schedule, so first schedule: 2 calls (throw+success),
        # second schedule: 1 call (success). Total 3.
        assert call_state["count"] == 3

    @patch("f.switchboard.check_gmail_watch_health.time.sleep", return_value=None)
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_persistent_error_flagged_after_retry(self, mock_requests, _sleep):
        mock_requests.get.side_effect = Exception("persistent failure")
        problems = check_schedules_enabled(TOKEN)
        assert len(problems) == 2
        assert all("check failed" in p for p in problems)

    @patch("f.switchboard.check_gmail_watch_health.time.sleep", return_value=None)
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_throw_then_404_reports_as_missing_not_check_failed(self, mock_requests, _sleep):
        """Regression guard: after a throw on attempt 0, a clean 404 on
        attempt 1 should flag the schedule as missing, not as 'check failed'."""
        state = {"idx": 0}

        def responses(url, **kw):
            state["idx"] += 1
            # First call on first schedule throws; retry returns 404
            if state["idx"] == 1:
                raise Exception("blip")
            if state["idx"] == 2:
                return _schedule_response(status=404, body={})
            return _schedule_response(enabled=True)

        mock_requests.get.side_effect = responses
        problems = check_schedules_enabled(TOKEN)
        assert len(problems) == 1
        assert "check failed" not in problems[0]


# ---------------------------------------------------------------------------
# Alert delivery status tracking
# ---------------------------------------------------------------------------

class TestAlertDeliveryStatus:
    @patch("f.switchboard.check_gmail_watch_health.psycopg2")
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_sms_gateway_ok_returns_alert_sent(self, mock_requests, mock_psycopg2):
        _setup_wmill_vars()
        mock_requests.get.return_value = _schedule_response(enabled=True)
        mock_psycopg2.connect.return_value = _fake_conn({"leads": 200, "teamgotcher": 0.5})
        mock_requests.post.side_effect = lambda url, **kw: (
            _sms_response(ok=True) if SMS_URL in url else _renewal_success()
        )

        result = main()
        assert result["status"] == "alert_sent"
        assert result["alert_delivered"] is True

    @patch("f.switchboard.check_gmail_watch_health.psycopg2")
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_sms_gateway_down_returns_alert_failed(self, mock_requests, mock_psycopg2):
        _setup_wmill_vars()
        mock_requests.get.return_value = _schedule_response(enabled=True)
        mock_psycopg2.connect.return_value = _fake_conn({"leads": 200, "teamgotcher": 0.5})
        mock_requests.post.side_effect = lambda url, **kw: (
            _sms_response(ok=False) if SMS_URL in url else _renewal_success()
        )

        result = main()
        assert result["status"] == "alert_failed"
        assert result["alert_delivered"] is False


# ---------------------------------------------------------------------------
# Bootstrap failure — wmill.get_variable raises
# ---------------------------------------------------------------------------

class TestBootstrapFailure:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_variable_fetch_failure_still_alerts(self, mock_requests):
        _wmill_mock.get_variable = MagicMock(side_effect=Exception("variable missing"))
        mock_requests.post.return_value = _sms_response(ok=True)

        result = main()

        assert result["status"] == "error"
        assert result["reason"] == "bootstrap_failed"
        assert result["alert_delivered"] is True
        # Fallback SMS URL was used
        assert any(
            "100.125.176.16:8686" in str(c)
            for c in mock_requests.post.call_args_list
        )


# ---------------------------------------------------------------------------
# Top-level error envelope — run_checks raises
# ---------------------------------------------------------------------------

class TestTopLevelErrorEnvelope:
    @patch("f.switchboard.check_gmail_watch_health.run_checks")
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_unexpected_error_caught_and_alerted(self, mock_requests, mock_run):
        _setup_wmill_vars()
        mock_run.side_effect = RuntimeError("boom")
        mock_requests.post.return_value = _sms_response(ok=True)

        result = main()

        assert result["status"] == "error"
        assert "boom" in result["error"]
        assert result["alert_delivered"] is True


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestCheckAccountStaleness:
    def test_returns_none_when_no_rows(self):
        conn = _fake_conn({"leads": None})
        hours, ts = check_account_staleness(conn, "leads")
        assert hours is None
        assert ts is None

    def test_returns_hours_for_recent_row(self):
        conn = _fake_conn({"leads": 3})
        hours, ts = check_account_staleness(conn, "leads")
        assert 2 < hours < 4
        assert ts is not None


class TestAttemptSelfHeal:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_both_queued(self, mock_requests):
        mock_requests.post.return_value = _renewal_success()
        results = attempt_self_heal(TOKEN)
        assert len(results) == 2
        assert all(r["success"] for r in results)

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_failure_captured(self, mock_requests):
        bad = MagicMock()
        bad.status_code = 500
        bad.text = "oauth revoked"
        mock_requests.post.return_value = bad
        results = attempt_self_heal(TOKEN)
        assert all(not r["success"] for r in results)
        assert "oauth revoked" in results[0]["error"]


class TestFormatAlert:
    def test_includes_each_issue_and_queued_note(self):
        issues = ["leads@ webhook stale (200h)", "schedule X missing or disabled"]
        heal = [
            {"script": "setup_gmail_watch", "account": "teamgotcher@", "success": True, "note": "queued"},
            {"script": "setup_gmail_leads_watch", "account": "leads@", "success": True, "note": "queued"},
        ]
        msg = format_alert(issues, heal)
        assert "leads@ webhook stale" in msg
        assert "missing or disabled" in msg
        assert "Auto-renewal queued" in msg

    def test_flags_self_heal_failures(self):
        issues = ["leads@ webhook stale (200h)"]
        heal = [
            {"script": "setup_gmail_watch", "account": "teamgotcher@", "success": False, "error": "revoked"},
            {"script": "setup_gmail_leads_watch", "account": "leads@", "success": False, "error": "revoked"},
        ]
        msg = format_alert(issues, heal)
        assert "Self-heal FAILED" in msg
        assert "revoked" in msg


class TestTrySendAlert:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_hardcoded_fallback_when_sms_url_none(self, mock_requests):
        mock_requests.post.return_value = _sms_response(ok=True)
        delivered = try_send_alert(None, "test")
        assert delivered is True
        args, _ = mock_requests.post.call_args
        assert "100.125.176.16:8686" in args[0]

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_returns_false_on_gateway_non_2xx(self, mock_requests):
        mock_requests.post.return_value = _sms_response(ok=False)
        assert try_send_alert(SMS_URL, "test") is False

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_returns_false_on_exception(self, mock_requests):
        mock_requests.post.side_effect = ConnectionError("down")
        assert try_send_alert(SMS_URL, "test") is False


class TestSendAlert:
    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_sends_payload_with_jake_number(self, mock_requests):
        mock_requests.post.return_value = _sms_response(ok=True)
        send_alert(SMS_URL, "hello")
        _, kwargs = mock_requests.post.call_args
        assert kwargs["json"]["phone"] == "+17348960518"
        assert "[RRG Alert] hello" in kwargs["json"]["message"]

    @patch("f.switchboard.check_gmail_watch_health.requests")
    def test_returns_false_on_exception(self, mock_requests):
        mock_requests.post.side_effect = ConnectionError("Network down")
        assert send_alert(SMS_URL, "x") is False
