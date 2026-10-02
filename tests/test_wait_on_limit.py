"""`--wait-on-limit`: the reset time read from the usage-limit message, and `run` / `grade` carrying on after it
(time frozen, sleeps recorded, no model calls)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner
from test_claude_judge import CC_JUDGE, GOOD, LIMIT, fake_claude, ungraded  # noqa: F401 - fixtures
from test_stop_on_limit import FakeClaude, answered, cli_run, limited  # noqa: F401 - fixture

from cbioportal_mcp_qa import cli as cli_mod
from cbioportal_mcp_qa import limits
from cbioportal_mcp_qa.limits import LimitWaiter, reset_time
from cbioportal_mcp_qa.run import Run

HNL = ZoneInfo("Pacific/Honolulu")
NOW = datetime(2026, 10, 1, 21, 0, tzinfo=HNL)


@pytest.mark.parametrize(
    "message, expected",
    [
        ("You've hit your session limit · resets 9:50pm (Pacific/Honolulu)", datetime(2026, 10, 1, 21, 50)),
        # Named in another zone: 21:00 HST is 07:00 UTC on the 2nd, so the next 3:40am UTC is on the 3rd.
        ("You've hit your limit · resets 3:40am (UTC)", datetime(2026, 10, 2, 17, 40)),
        # Earlier in the day than now: tomorrow's.
        ("You've hit your limit · resets 8am (Pacific/Honolulu)", datetime(2026, 10, 2, 8, 0)),
        ("You've hit your limit · resets 12am (Pacific/Honolulu)", datetime(2026, 10, 2, 0, 0)),
        ("You've hit your limit · resets 12:30pm (Pacific/Honolulu)", datetime(2026, 10, 2, 12, 30)),
        ("Claude usage limit reached · resets 11 PM (Pacific/Honolulu)", datetime(2026, 10, 1, 23, 0)),
    ],
)
def test_reset_time_is_the_next_such_time(message, expected):
    assert reset_time(message, NOW).astimezone(HNL).replace(tzinfo=None) == expected


def test_reset_time_without_a_zone_is_local_time(monkeypatch):
    monkeypatch.setenv("TZ", "Pacific/Honolulu")
    import time

    time.tzset()
    try:
        reset = reset_time("You've hit your session limit · resets 3pm", NOW)
        assert reset.astimezone(HNL).replace(tzinfo=None) == datetime(2026, 10, 2, 15, 0)
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


@pytest.mark.parametrize(
    "message",
    [
        "You've hit your weekly limit · resets Oct 3",
        "You've hit your weekly Opus limit · resets Mon",
        "Claude usage limit reached",
        "You've hit your limit · resets 9pm (Mars/Olympus)",  # not a zone
        "You've hit your limit · resets 13pm (UTC)",
        "You've hit your limit · resets 8:30pm (Pacific/Honolulu)",  # just passed: about to clear
    ],
)
def test_reset_time_unreadable_or_just_passed_is_none(message):
    assert reset_time(message, NOW) is None


@pytest.fixture
def frozen(monkeypatch):
    """Time frozen at NOW; sleeps are recorded instead of slept."""
    slept: list[float] = []
    monkeypatch.setattr(limits, "_now", lambda: NOW)
    monkeypatch.setattr(limits.time, "sleep", slept.append)
    return slept


def test_waiter_sleeps_to_the_reset_or_backs_off_and_keeps_to_max_wait(frozen):
    waiter = LimitWaiter(max_wait_s=90 * 60)
    assert waiter.wait("You've hit your limit · resets 9:50pm (Pacific/Honolulu)")
    assert frozen == [50 * 60 + limits.MARGIN_S]
    assert waiter.wait("You've hit your weekly limit · resets Oct 3")  # fixed back-off
    assert frozen[-1] == limits.BACKOFF_S
    # 51 + 15 min used of 90: a wait to 10:30pm (91 min) would pass --max-wait, so it stops without sleeping.
    assert not waiter.wait("You've hit your limit · resets 10:30pm (Pacific/Honolulu)")
    assert len(frozen) == 2


def test_run_waits_for_the_reset_then_answers_the_rest(monkeypatch, results_dir, cli_run, frozen):  # noqa: F811
    state = {"limited": True}

    def script(question, n):
        if n == 3 and state["limited"]:
            return limited(), 0.0
        return answered(), 0.0

    def sleep(seconds):
        frozen.append(seconds)
        state["limited"] = False  # the limit resets while it sleeps

    monkeypatch.setattr(limits.time, "sleep", sleep)
    fake = FakeClaude(monkeypatch, script)
    out = cli_run(fake, "--questions", "1-6", "--concurrency", "1", "--wait-on-limit")
    assert out.exit_code == 0, out.output
    assert frozen == [50 * 60 + limits.MARGIN_S]
    assert "waiting 51 min, until 2026-10-01 21:51 HST" in out.output
    # Q3 hit the limit and was asked again after the wait: 6 answers in 7 sessions, none failed.
    assert len(fake.asked) == 7 and fake.asked[2] == fake.asked[3]
    run = Run.load(next(p for p in results_dir.iterdir() if (p / "run.json").exists()).name)
    assert len(run.records) == 6 and all(r["reply"]["status"] == 200 for r in run.records.values())


def test_run_stops_when_the_wait_would_pass_max_wait(monkeypatch, results_dir, cli_run, frozen):  # noqa: F811
    fake = FakeClaude(monkeypatch, lambda q, n: (limited(), 0.0) if n == 2 else (answered(), 0.0))
    out = cli_run(fake, "--questions", "1-4", "--concurrency", "1", "--wait-on-limit", "--max-wait", "30")
    assert out.exit_code == 1, out.output
    assert frozen == []
    assert "would pass --max-wait" in out.output and "--resume" in out.output


def test_grade_waits_for_the_reset_then_grades_the_rest(fake_claude, ungraded, frozen, monkeypatch):  # noqa: F811
    fake_claude.set(GOOD, LIMIT, GOOD)  # LIMIT says "resets 5pm": local time
    monkeypatch.setattr(limits, "_now", lambda: datetime(2026, 10, 1, 16, 0).astimezone())
    result = CliRunner().invoke(
        cli_mod.cli, ["grade", str(ungraded.dir), "--judge-runner", "claude-code", "--wait-on-limit"]
    )
    assert result.exit_code == 0, result.output
    assert frozen == [60 * 60 + limits.MARGIN_S]
    run = Run.load(str(ungraded.dir))
    assert all(r["grade"]["judge_model"] == CC_JUDGE for r in run.records.values())
    assert not any("judge_error" in r for r in run.records.values())
    assert len(fake_claude.calls) == 4  # the limited call is made again after the wait


def test_grade_without_the_flag_still_stops(fake_claude, ungraded, frozen):  # noqa: F811
    fake_claude.set(GOOD, LIMIT)
    result = CliRunner().invoke(cli_mod.cli, ["grade", str(ungraded.dir), "--judge-runner", "claude-code"])
    assert result.exit_code == 1 and "grading stopped" in result.output
    assert frozen == []
    assert not any("judge_error" in r for r in Run.load(str(ungraded.dir)).records.values())
