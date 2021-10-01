"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""

from django import template

from itou.utils.perms.user import is_user_france_connected


register = template.Library()


@register.filter(name="user_is_france_connected")
def tag_is_user_france_connected(request):
    return is_user_france_connected(request)
