from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings


class DemoAccountAdapter(DefaultAccountAdapter):
    """
    Overrides standard allauth adapter:
        * provides additionnal context to some emails sent via allauth

    Activation of this adapter is done in project settings with:
        ACCOUNT_ADAPTER = "name_of_class"
    """

    def send_mail(self, template_prefix, email, context):
        context["itou_environment"] = settings.ITOU_ENVIRONMENT
        super().send_mail(template_prefix, email, context)
