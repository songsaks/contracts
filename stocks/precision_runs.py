"""Small, offline helpers for Precision scan data quality and history."""
import math


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
    ranks = {}
    for symbol, value in valid.items():
        # Average rank for ties, matching pandas rank(pct=True).
        lower = sum(v < value for v in values)
        equal = sum(v == value for v in values)
        ranks[symbol] = int((lower + (equal + 1) / 2) / len(values) * 99)
    return ranks, len(valid)


def scan_timestamps(candidate_times, runs):
    return sorted(set(candidate_times) | {r.started_at for r in runs}, reverse=True)
