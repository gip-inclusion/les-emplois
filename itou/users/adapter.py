from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.urls import reverse
from django.utils.http import urlencode

from itou.openid_connect.france_connect.constants import FRANCE_CONNECT_SESSION_STATE, FRANCE_CONNECT_SESSION_TOKEN
from itou.openid_connect.inclusion_connect.constants import INCLUSION_CONNECT_SESSION_KEY
from itou.openid_connect.pe_connect.constants import PE_CONNECT_SESSION_TOKEN
from itou.utils.urls import get_safe_url


class UserAdapter(DefaultAccountAdapter):
    """
    Overrides standard allauth adapter:
        * sets user kind on save
        * provides additional context to some emails sent via allauth
        * handles redirections after allauth actions

    Activation of this adapter is done in project settings with:
        ACCOUNT_ADAPTER = "name_of_class"
    """

    def save_user(self, request, user, form):
        user.kind = form.user_kind
        return super().save_user(request, user, form)

    def get_login_redirect_url(self, request):
        url = reverse("dashboard:index")
        # In demo, false accounts are used by many different persons but never recreated.
        # The welcoming tour should show up anyway.
        if not request.user.has_completed_welcoming_tour or settings.ITOU_ENVIRONMENT == "DEMO":
            url = reverse("welcoming_tour:index")
        return url

    def get_logout_redirect_url(self, request):
        """
        Returns the URL to redirect to after the user logs out. Note that
        this method is also invoked if you attempt to log out while no user
        is logged in. Therefore, request.user is not guaranteed to be an
        authenticated user.
        Tests are in itou.inclusion_connect.tests.
        """
        redirect_url = reverse("search:employers_home")
        # Inclusion Connect
        ic_session = request.session.get(INCLUSION_CONNECT_SESSION_KEY)
        if ic_session:
            token = ic_session["token"]
            if token:
                params = {"token": token}
                ic_base_logout_url = reverse("inclusion_connect:logout")
                return f"{ic_base_logout_url}?{urlencode(params)}"
        # France Connect
        fc_token = request.session.get(FRANCE_CONNECT_SESSION_TOKEN)
        fc_state = request.session.get(FRANCE_CONNECT_SESSION_STATE)
        if fc_token:
            params = {"id_token": fc_token, "state": fc_state}
            fc_base_logout_url = reverse("france_connect:logout")
            return f"{fc_base_logout_url}?{urlencode(params)}"
        # PE Connect
        pe_token = request.session.get(PE_CONNECT_SESSION_TOKEN)
        if pe_token:
            params = {"id_token": pe_token}
            pe_base_logout_url = reverse("pe_connect:logout")
            return f"{pe_base_logout_url}?{urlencode(params)}"
        return redirect_url

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
