"""Small, offline helpers for Precision scan data quality and history."""
import math
from bisect import bisect_left, bisect_right


def rank_valid_returns(returns):
    valid = {}
    for symbol, value in returns.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            valid[symbol] = number
    if len(valid) < 10:
        return {}, len(valid)
    values = sorted(valid.values())
    n = len(values)
    ranks = {}
    # Average rank for ties, matching pandas rank(pct=True). The list is already
    # sorted, so binary-search the tie block instead of rescanning every value
    # per symbol — the old pair of sum() calls made this O(n^2) over the whole
    # scan universe, which is thousands of symbols on a full run.
    for symbol, value in valid.items():
        lower = bisect_left(values, value)
        equal = bisect_right(values, value) - lower
        ranks[symbol] = int((lower + (equal + 1) / 2) / n * 99)
    return ranks, len(valid)


def scan_timestamps(candidate_times, runs):
    return sorted(set(candidate_times) | {r.started_at for r in runs}, reverse=True)
