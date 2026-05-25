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
