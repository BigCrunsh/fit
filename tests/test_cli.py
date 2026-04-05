"""Smoke tests for all fit CLI commands — verify they run without crashing."""

from click.testing import CliRunner

from fit.cli import main


class TestCLICommands:
    """Every CLI command should at least run and exit 0 (or show help)."""

    def test_help(self):
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Personal fitness data platform" in result.output

    def test_version(self):
        result = CliRunner().invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_status(self):
        result = CliRunner().invoke(main, ["status"])
        assert result.exit_code == 0
        assert "fit" in result.output

    def test_doctor(self):
        result = CliRunner().invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "fit doctor" in result.output

    def test_correlate(self):
        result = CliRunner().invoke(main, ["correlate"])
        assert result.exit_code == 0

    def test_races(self):
        result = CliRunner().invoke(main, ["races"])
        assert result.exit_code == 0
        assert "Race Calendar" in result.output

    def test_goal_list(self):
        result = CliRunner().invoke(main, ["goal", "list"])
        assert result.exit_code == 0

    def test_goal_help(self):
        result = CliRunner().invoke(main, ["goal", "--help"])
        assert result.exit_code == 0
        assert "Manage training goals" in result.output

    def test_sync_help(self):
        result = CliRunner().invoke(main, ["sync", "--help"])
        assert result.exit_code == 0
        assert "--days" in result.output
        assert "--full" in result.output

    def test_checkin_help(self):
        result = CliRunner().invoke(main, ["checkin", "--help"])
        assert result.exit_code == 0

    def test_report_help(self):
        result = CliRunner().invoke(main, ["report", "--help"])
        assert result.exit_code == 0
        assert "--daily" in result.output
        assert "--weekly" in result.output

    def test_recompute_help(self):
        result = CliRunner().invoke(main, ["recompute", "--help"])
        assert result.exit_code == 0

    def test_calibrate_help(self):
        result = CliRunner().invoke(main, ["calibrate", "--help"])
        assert result.exit_code == 0
        assert "max_hr" in result.output
        assert "lthr" in result.output

    def test_report_generates(self):
        """fit report should generate the dashboard HTML."""
        result = CliRunner().invoke(main, ["report"])
        assert result.exit_code == 0
        assert "dashboard.html" in result.output
