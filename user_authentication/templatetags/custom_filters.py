from django import template

register = template.Library()

@register.filter
def subtract(value, arg):
    return value - arg

@register.filter
def percentage(value, total):
    try:
        return int((value / total) * 100)
    except (ValueError, ZeroDivisionError):
        return 0
