from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.utils.http import urlencode

from itou.openid_connect.france_connect.constants import FRANCE_CONNECT_SESSION_STATE, FRANCE_CONNECT_SESSION_TOKEN
from itou.openid_connect.pe_connect.constants import PE_CONNECT_SESSION_TOKEN
from itou.openid_connect.pro_connect.constants import PRO_CONNECT_SESSION_KEY
from itou.utils.urls import get_absolute_url, get_safe_url


class UserAdapter(DefaultAccountAdapter):
    """
    Overrides standard allauth adapter:
        * sets user kind on save
        * provides additional context to some emails sent via allauth
        * handles redirections after allauth actions

    Activation of this adapter is done in project settings with:
        ACCOUNT_ADAPTER = "name_of_class"
    """

    def add_message(self, request, level, message_template=None, message_context=None, extra_tags="", message=None):
        if level == messages.SUCCESS:
            extra_tags = extra_tags.split()
            extra_tags.append("toast")
            extra_tags = " ".join(extra_tags)
        super().add_message(
            request,
            level,
            message_template=message_template,
            message_context=message_context,
            extra_tags=extra_tags,
            message=message,
        )

    def save_user(self, request, user, form):
        user.kind = form.user_kind
        return super().save_user(request, user, form)

    def get_signup_redirect_url(self, request):
        return self.get_login_redirect_url(request)

    def get_login_redirect_url(self, request):
        url = reverse("dashboard:index")
        if not request.user.has_completed_welcoming_tour:
            url = reverse("welcoming_tour:index")
        return url

    def get_logout_redirect_url(self, request):
        """
        Returns the URL to redirect to after the user logs out. Note that
        this method is also invoked if you attempt to log out while no user
        is logged in. Therefore, request.user is not guaranteed to be an
        authenticated user.
        Tests are in itou.openid_connect.***.tests.
        """
        redirect_url = reverse("search:employers_home")
        # ProConnect
        pro_session = request.session.get(PRO_CONNECT_SESSION_KEY)
        if pro_session:
            token = pro_session["token"]
            if token:
                params = {"token": token}
                pro_connect_base_logout_url = reverse("pro_connect:logout")
                return f"{pro_connect_base_logout_url}?{urlencode(params)}"
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
        next_url = get_safe_url(request, "next")
        url = super().get_email_confirmation_url(request, emailconfirmation)
        if next_url:
            url = f"{url}?next={next_url}"
        return url

    def get_email_verification_redirect_url(self, email_address):
        """
        Redirection performed after a user confirmed its email address.
        """
        next_url = get_safe_url(self.request, "next")
        url = super().get_email_verification_redirect_url(email_address)
        if next_url:
            url = next_url
        return url

    def send_mail(self, template_prefix, email, context):
        context["itou_environment"] = settings.ITOU_ENVIRONMENT
        context["itou_protocol"] = settings.ITOU_PROTOCOL
        context["itou_fqdn"] = settings.ITOU_FQDN
        context["base_url"] = get_absolute_url()
        context["signup_url"] = get_absolute_url(reverse("signup:choose_user_kind"))
        super().send_mail(template_prefix, email, context)
