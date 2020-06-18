from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings

print("Using demo adpater")

class DemoAccountAdapter(DefaultAccountAdapter):

    def send_mail(self, template_prefix, email, context):
        context["itou_environment"] = settings.ITOU_ENVIRONMENT
        super().send_mail(template_prefix, email, context)
