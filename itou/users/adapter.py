from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.urls import reverse

from itou.utils.urls import get_safe_url


class UserAdapter(DefaultAccountAdapter):
    """
    Overrides standard allauth adapter:
        * provides additionnal context to some emails sent via allauth
        * handles redirections after allauth actions

    Activation of this adapter is done in project settings with:
        ACCOUNT_ADAPTER = "name_of_class"
    """

    def get_login_redirect_url(self, request):
        url = reverse("dashboard:index")
        # In demo, false accounts are used by many different persons but never recreated.
        # The welcoming tour should show up anyway.
        if not request.user.has_completed_welcoming_tour or settings.ITOU_ENVIRONMENT == "REVIEW_APP":
            # TODO: replace environment by DEMO after review
            url = reverse("welcoming_tour:index")
        return url

    def get_email_confirmation_url(self, request, emailconfirmation):
        """
        Return an absolute url to be displayed in the email
        sent to users to confirm their email address.
        """
        next_url = request.POST.get("next") or request.GET.get("next")
        url = super().get_email_confirmation_url(request, emailconfirmation)
        if next_url:
            url = f"{url}?next={get_safe_url(request, 'next')}"
        return url

    def get_email_confirmation_redirect_url(self, request):
        """
        Redirection performed after a user confirmed its email address.
        """
        next_url = request.POST.get("next") or request.GET.get("next")
        url = super().get_email_confirmation_redirect_url(request)
        if next_url:
            url = get_safe_url(request, "next")
        return url

    def send_mail(self, template_prefix, email, context):
        context["itou_environment"] = settings.ITOU_ENVIRONMENT
        super().send_mail(template_prefix, email, context)
