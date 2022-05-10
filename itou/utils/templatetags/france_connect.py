"""
https://docs.djangoproject.com/en/dev/howto/custom-template-tags/
"""

from django import template

from itou.users.enums import IdentityProvider


register = template.Library()


@register.filter(name="user_is_france_connected")
def tag_is_user_france_connected(request):
    return request.user.identity_provider == IdentityProvider.FRANCE_CONNECT
