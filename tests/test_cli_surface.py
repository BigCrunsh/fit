"""CLI surface contract (tidy-cli-surface): canonical names present, deprecated aliases hidden
but still wired, and the new flags added. Introspects the click command tree (no DB/network) plus
one behavioral guard."""

from click.testing import CliRunner

from fit.cli import main


def _opts(cmd):
    return [p.name for p in main.commands[cmd].params]


class TestCliSurface:
    def test_objective_is_canonical(self):
        assert "objective" in main.commands
        assert set(main.commands["objective"].commands) >= {"set", "show", "clear"}

    def test_target_is_a_hidden_deprecated_alias(self):
        assert "target" in main.commands and main.commands["target"].hidden is True
        # the alias group still carries the same subcommands (forwarding to objective)
        assert set(main.commands["target"].commands) >= {"set", "show", "clear"}

    def test_coach_command_present(self):
        assert "coach" in main.commands

    def test_plan_sync_renamed_old_name_hidden(self):
        plan = main.commands["plan"]
        assert "sync-calendar" in plan.commands
        assert "sync" in plan.commands and plan.commands["sync"].hidden is True

    def test_calibrate_gains_history_flag(self):
        assert "history" in _opts("calibrate")
        # calibrate-history stays (broader metric set incl. aet/vo2max/weight) — NOT removed
        assert "calibrate-history" in main.commands

    def test_sync_gains_backfill_flag_alongside_splits(self):
        assert "backfill" in _opts("sync") and "splits" in _opts("sync")

    def test_splits_keeps_one_off_and_deprecated_backfill(self):
        opts = _opts("splits")
        assert "activity_id" in opts and "backfill" in opts

    def test_sync_backfill_requires_splits(self):
        # errors BEFORE any DB/network — the guard is first
        r = CliRunner().invoke(main, ["sync", "--backfill"])
        assert r.exit_code == 2 and "applies to --splits" in r.output
