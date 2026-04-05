"""Tests for fit/correlations.py — Spearman rank, pairing, thresholds."""

from fit.correlations import _rank, _spearman_r, _pearson_r, _p_value, _norm_cdf


class TestRank:
    def test_simple_ranking(self):
        assert _rank([3, 1, 2]) == [3.0, 1.0, 2.0]

    def test_tied_values(self):
        ranks = _rank([1, 2, 2, 3])
        assert ranks[1] == ranks[2]  # tied
        assert ranks[1] == 2.5  # average rank

    def test_all_same(self):
        ranks = _rank([5, 5, 5])
        assert ranks == [2.0, 2.0, 2.0]

    def test_single_value(self):
        assert _rank([42]) == [1.0]

    def test_already_sorted(self):
        assert _rank([1, 2, 3, 4]) == [1.0, 2.0, 3.0, 4.0]

    def test_reverse_sorted(self):
        assert _rank([4, 3, 2, 1]) == [4.0, 3.0, 2.0, 1.0]


class TestSpearmanR:
    def test_perfect_positive(self):
        r = _spearman_r([1, 2, 3, 4, 5], [10, 20, 30, 40, 50])
        assert r is not None
        assert abs(r - 1.0) < 0.01

    def test_perfect_negative(self):
        r = _spearman_r([1, 2, 3, 4, 5], [50, 40, 30, 20, 10])
        assert r is not None
        assert abs(r + 1.0) < 0.01

    def test_no_correlation(self):
        r = _spearman_r([1, 2, 3, 4, 5], [3, 1, 4, 5, 2])
        assert r is not None
        assert abs(r) < 0.5

    def test_too_few_points(self):
        assert _spearman_r([1, 2], [3, 4]) is None

    def test_empty(self):
        assert _spearman_r([], []) is None

    def test_ordinal_data(self):
        """Spearman should handle ordinal data (sleep_quality: 1=Poor, 2=OK, 3=Good)."""
        r = _spearman_r([1, 1, 2, 2, 3, 3], [40, 45, 60, 65, 80, 85])
        assert r is not None
        assert r > 0.8  # strong positive


class TestPearsonR:
    def test_perfect_linear(self):
        r = _pearson_r([1, 2, 3], [2, 4, 6])
        assert r is not None
        assert abs(r - 1.0) < 0.01

    def test_constant_returns_none(self):
        assert _pearson_r([1, 1, 1], [2, 3, 4]) is None

    def test_too_few(self):
        assert _pearson_r([1], [2]) is None


class TestPValue:
    def test_strong_correlation_low_p(self):
        p = _p_value(0.9, 30)
        assert p is not None
        assert p < 0.01

    def test_weak_correlation_high_p(self):
        p = _p_value(0.1, 10)
        assert p is not None
        assert p > 0.1

    def test_too_few_samples(self):
        assert _p_value(0.5, 3) is None

    def test_r_equals_1(self):
        assert _p_value(1.0, 10) is None

    def test_r_none(self):
        assert _p_value(None, 10) is None


class TestNormCDF:
    def test_zero(self):
        assert abs(_norm_cdf(0) - 0.5) < 0.01

    def test_large_positive(self):
        assert _norm_cdf(4) > 0.999

    def test_large_negative(self):
        assert _norm_cdf(-4) < 0.001
