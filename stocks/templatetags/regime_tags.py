from django import template
from django.core.cache import cache

register = template.Library()

_STRATEGY = {
    ('TRENDING', True):  {'label': 'ใช้ Turtle / Momentum Scanner', 'color': 'success', 'icon': 'fa-arrow-trend-up', 'link': 'stocks:turtle_scanner'},
    ('TRENDING', False): {'label': 'Turtle selective — ลด Position Size', 'color': 'warning', 'icon': 'fa-triangle-exclamation', 'link': 'stocks:turtle_scanner'},
    ('CHOPPY', None):    {'label': 'ตลาด Sideways — ใช้ Mean Reversion Scanner', 'color': 'warning', 'icon': 'fa-left-right', 'link': 'stocks:mean_reversion_scanner'},
    ('BEARISH', None):   {'label': 'ตลาดขาลง — พักการซื้อ / ถือ Cash', 'color': 'danger', 'icon': 'fa-circle-xmark', 'link': None},
}


def _get_strategy(regime):
    state = regime.get('state', 'UNKNOWN')
    prob  = regime.get('prob', 0)
    if state == 'TRENDING':
        key = ('TRENDING', prob >= 60)
    elif state in ('CHOPPY', 'ACCUMULATING', 'DISTRIBUTING'):
        key = ('CHOPPY', None)
    elif state == 'BEARISH':
        key = ('BEARISH', None)
    else:
        return {'label': 'ไม่มีข้อมูล Regime', 'color': 'secondary', 'icon': 'fa-circle-question', 'link': None}
    return _STRATEGY.get(key, {'label': '—', 'color': 'secondary', 'icon': 'fa-circle-question', 'link': None})


@register.filter
def split(value, arg):
    """Split a string by delimiter — e.g. "50,60,70"|split:"," → ['50','60','70']"""
    return str(value).split(arg)


@register.filter
def get_item(dictionary, key):
    """Get value from dictionary using key"""
    if not dictionary:
        return None
    return dictionary.get(key)



@register.inclusion_tag('stocks/includes/_regime_bar.html')
def regime_bar(market='SET'):
    from stocks.utils import calculate_markov_regime
    cache_key = f'markov_regime_global_{market}'
    regime = cache.get(cache_key)
    if not regime:
        index_sym = '^SET' if market == 'SET' else '^GSPC'
        regime = calculate_markov_regime(index_sym)
        cache.set(cache_key, regime, 1800)
    return {'regime': regime, 'strategy': _get_strategy(regime), 'market': market}


@register.filter
def ehlers_tooltip(obj):
    """
    Generate Ehlers Indicators tooltip with summary and recommendation.
    Can accept a dict, StockScan model instance, or portfolio item dict.
    """
    if not obj:
        return "ไม่มีข้อมูล Ehlers"

    def get_val(o, keys, default=None):
        for k in keys:
            if isinstance(o, dict):
                val = o.get(k)
            else:
                val = getattr(o, k, None)
            if val is not None:
                return val
        return default

    mom_data = get_val(obj, ['mom_data'])
    target = mom_data if mom_data else obj

    supersmoother = get_val(target, ['ehlers_supersmoother'])
    laguerre_rsi = get_val(target, ['ehlers_laguerre_rsi'])
    fisher = get_val(target, ['ehlers_fisher'])
    fisher_trigger = get_val(target, ['ehlers_fisher_trigger'])
    price = get_val(obj, ['price', 'current_price', 'close']) or get_val(target, ['price', 'current_price', 'close'])
    rsi = get_val(obj, ['rsi']) or get_val(target, ['rsi'])

    lines = []
    if rsi is not None and rsi != '':
        try:
            lines.append(f"RSI (โมเมนตัม 14 วัน): {float(rsi):.0f}")
        except (ValueError, TypeError):
            pass

    lines.append("Ehlers Indicators:")

    def fmt(val):
        if val is None or val == '' or val == '-':
            return "-"
        try:
            return f"{float(val):.2f}"
        except (ValueError, TypeError):
            return "-"

    ss_str = fmt(supersmoother)
    lrsi_str = fmt(laguerre_rsi)
    fish_str = fmt(fisher)
    trig_str = fmt(fisher_trigger)

    lines.append(f"• SuperSmoother: {ss_str}")
    lines.append(f"• Laguerre RSI: {lrsi_str}")
    lines.append(f"• Fisher: {fish_str} (Trigger: {trig_str})")
    lines.append("----------------------------------------")

    try:
        lrsi_v = float(laguerre_rsi) if laguerre_rsi not in (None, '', '-') else None
        p_v = float(price) if price not in (None, '', '-') else None
        ss_v = float(supersmoother) if supersmoother not in (None, '', '-') else None
        fish_v = float(fisher) if fisher not in (None, '', '-') else None
        trig_v = float(fisher_trigger) if fisher_trigger not in (None, '', '-') else None
    except (ValueError, TypeError):
        lrsi_v = p_v = ss_v = fish_v = trig_v = None

    summary = "โมเมนตัมเป็นกลาง แกว่งตัวสร้างฐาน"
    action = "เฝ้าสังเกตการณ์ รอดูการเลือกทาง"

    if lrsi_v is not None:
        if lrsi_v >= 0.80:
            summary = "ขึ้นแรงติดลมบน (Super Bullish)"
            action = "รันเทรนด์ต่อ (Let Profit Run) / ขยับ Stop Loss ตาม"
        elif lrsi_v >= 0.15 and fish_v is not None and trig_v is not None and fish_v > trig_v:
            summary = "เพิ่งกลับตัวขึ้น ยืนยันการฟื้นตัวจากฐาน"
            action = "เริ่มทยอยสะสมหุ้น (Buy on Reversal)"
        elif lrsi_v >= 0.40:
            if p_v is not None and ss_v is not None and p_v < ss_v:
                summary = f"พักตัว แต่ราคาหลุดแนวรับ SuperSmoother ({p_v:.2f} < {ss_v:.2f})"
                action = f"ชะลอการซื้อเพิ่ม รอดูราคากลับมายืนเหนือ {ss_str}"
            else:
                summary = "พักตัวเพื่อขึ้นต่อ (Buy on Pullback)"
                action = "จังหวะย่อซื้อความเสี่ยงต่ำ / วาง Stop Loss ใต้ SuperSmoother"
        elif lrsi_v < 0.15:
            summary = "โมเมนตัมอ่อนแรงลึก (Oversold)"
            action = "ชะลอการซื้อ รอดูสัญญาณ Fisher ตัดขึ้นก่อน"

    lines.append(f"📌 สรุป: {summary}")
    lines.append(f"💡 แนะนำ: {action}")

    return "\n".join(lines)

