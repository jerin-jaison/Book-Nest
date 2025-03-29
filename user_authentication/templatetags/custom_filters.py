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

@register.filter
def is_product_offer(offer):
    """Check if an offer is a product offer"""
    from admin_side.models import ProductOffer
    return isinstance(offer, ProductOffer)

@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using the key"""
    if dictionary is None:
        return None
    return dictionary.get(key)
