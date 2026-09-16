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


def entry_risk_reward(price, stop, target):
    try:
        price, stop, target = map(float, (price, stop, target))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (price, stop, target)):
        return None
    if not 0 < stop < price < target:
        return None
    return (target - price) / (price - stop)


def average_daily_turnover(df):
    rows = df[['Close', 'Volume']].tail(20)
    if len(rows) < 20 or rows.isna().any().any():
        raise ValueError('Incomplete 20-session liquidity data')
    values = []
    for price, volume in rows.itertuples(index=False, name=None):
        price, volume = float(price), float(volume)
        if not math.isfinite(price) or not math.isfinite(volume) or price <= 0 or volume < 0:
            raise ValueError('Invalid liquidity data')
        values.append(price * volume)
    return sum(values) / len(values)


def deep_scan_outcome(passed, rejected, failed):
    if failed and passed + rejected == 0:
        return 'failed', f'สแกนรายละเอียดล้มเหลว {failed} ตัว ไม่มีผลวิเคราะห์ที่ใช้ได้ กรุณาลองใหม่'
    if failed:
        return 'completed', f'ผลไม่ครบ: ผ่าน {passed} ตัว ไม่ผ่านเกณฑ์ {rejected} ตัว วิเคราะห์ล้มเหลว {failed} ตัว'
    return 'completed', ''
