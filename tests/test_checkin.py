"""Tests for fit/checkin.py — alcohol parsing."""

import pytest

from fit.checkin import _parse_alcohol


# ════════════════════════════════════════════════════════════════
# Alcohol Parsing
# ════════════════════════════════════════════════════════════════


class TestParseAlcohol:
    # Happy
    def test_zero(self):
        count, detail = _parse_alcohol("0")
        assert count == 0
        assert detail is None

    def test_number_with_description(self):
        count, detail = _parse_alcohol("2 beers")
        assert count == 2.0
        assert detail == "2 beers"

    def test_number_only(self):
        count, detail = _parse_alcohol("3")
        assert count == 3.0
        assert detail == "3"

    def test_float_number(self):
        count, detail = _parse_alcohol("1.5 glasses")
        assert count == 1.5
        assert detail == "1.5 glasses"

    def test_one_beer(self):
        count, detail = _parse_alcohol("1 beer")
        assert count == 1.0
        assert detail == "1 beer"

    # Unhappy
    def test_empty_string(self):
        count, detail = _parse_alcohol("")
        assert count == 0
        assert detail is None

    def test_text_only_assumes_one(self):
        """Text without leading number assumes 1 serving."""
        count, detail = _parse_alcohol("small glass wine")
        assert count == 1.0
        assert detail == "small glass wine"

    def test_abc_non_numeric(self):
        count, detail = _parse_alcohol("abc")
        assert count == 1.0
        assert detail == "abc"

    def test_just_text_word(self):
        count, detail = _parse_alcohol("beer")
        assert count == 1.0
        assert detail == "beer"

    def test_negative_number(self):
        """Negative number: float('-1') works, so count=-1."""
        count, detail = _parse_alcohol("-1 drink")
        assert count == -1.0
        assert detail == "-1 drink"

    def test_zero_string(self):
        count, detail = _parse_alcohol("0")
        assert count == 0
        assert detail is None

    def test_zero_with_text(self):
        """'0 beers' — leading 0 is parsed as number."""
        count, detail = _parse_alcohol("0 beers")
        assert count == 0.0
        assert detail == "0 beers"

    def test_large_number(self):
        count, detail = _parse_alcohol("10 cocktails")
        assert count == 10.0
        assert detail == "10 cocktails"

    def test_whitespace_only(self):
        """Whitespace-only string: split(None, 1) returns [] → IndexError.
        This is an edge case that would be caught by the caller stripping first.
        The function itself raises IndexError on pure whitespace."""
        with pytest.raises(IndexError):
            _parse_alcohol("   ")

    def test_none_input(self):
        """None input should return (0, None) per the 'not s' check."""
        count, detail = _parse_alcohol(None)
        assert count == 0
        assert detail is None
