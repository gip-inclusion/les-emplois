from django import template

from itou.otp.utils import user_can_manage_otp_devices


register = template.Library()


@register.simple_tag
def show_otp_configuration(user):
    # Same predicate as the OTP views, so that the menu only shows what is reachable
    return user.is_authenticated and user_can_manage_otp_devices(user)
