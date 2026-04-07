"""Tests for fit doctor diagnostic command."""

from click.testing import CliRunner

from fit.cli import main


class TestDoctor:
    def test_doctor_runs(self):
        """fit doctor should run without crashing."""
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0
        assert "Doctor" in result.output

    def test_doctor_shows_schema(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert "Schema" in result.output

    def test_doctor_shows_tables(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert "Tables" in result.output

    def test_doctor_checks_calibration(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert "calibration" in result.output.lower()

    def test_doctor_checks_data_sources(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert "data source" in result.output.lower() or "issue" in result.output.lower()
