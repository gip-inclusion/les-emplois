from django import template

from itou.otp.utils import user_is_concerned_by_otp


register = template.Library()


@register.simple_tag
def show_otp_configuration(user):
    return user.is_authenticated and user_is_concerned_by_otp(user)
