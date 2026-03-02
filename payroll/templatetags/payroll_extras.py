from django import template

register = template.Library()

@register.filter
def dict_get(dictionary, key):
    return dictionary.get(key)

_MONTH_NAMES = {
    1: 'มกราคม', 2: 'กุมภาพันธ์',  3: 'มีนาคม',
    4: 'เมษายน', 5: 'พฤษภาคม',     6: 'มิถุนายน',
    7: 'กรกฎาคม', 8: 'สิงหาคม',   9: 'กันยายน',
    10: 'ตุลาคม',11: 'พฤศจิกายน', 12: 'ธันวาคม',
}

@register.filter
def month_name(value):
    """Convert a month number (1-12) to Thai month name."""
    try:
        return _MONTH_NAMES.get(int(value), str(value))
    except (TypeError, ValueError):
        return value

@register.filter
def subtract(value, arg):
    """Subtract the arg from the value."""
    try:
        return value - arg
    except (TypeError, ValueError):
        return value

@register.filter
def split(value, arg):
    """Split the string by arg."""
    return value.split(arg)
