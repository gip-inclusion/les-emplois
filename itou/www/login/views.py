from allauth.account.internal.decorators import login_not_required
from allauth.account.views import LoginView
from allauth.decorators import rate_limit
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic.edit import FormView
from django_otp import login as otp_login

from itou.openid_connect.pro_connect.enums import ProConnectChannel
from itou.users.enums import IDENTITY_PROVIDER_SUPPORTED_USER_KIND, MATOMO_ACCOUNT_TYPE, IdentityProvider, UserKind
from itou.users.models import User
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.urls import get_safe_url, get_url_param_value
from itou.www.login.constants import ITOU_SESSION_LOGIN_EMAIL_KEY
from itou.www.login.forms import FindExistingUserViaEmailForm, ItouLoginForm, VerifyOTPForm


class UserKindLoginMixin:
    """
    Mixin class which adds functionality relating to the different IdentityProviders,
    configured to be used according to UserKind (certain identity providers accessible only to certain user kinds).
    django-allauth provides the login behaviour, extended by views for each UserKind.
    """

    def _get_pro_connect_url(self):
        if not settings.PRO_CONNECT_BASE_URL:
            return None

        if self.user.kind not in IDENTITY_PROVIDER_SUPPORTED_USER_KIND[IdentityProvider.PRO_CONNECT]:
            return None

        params = {
            "user_kind": self.user.kind,
            "previous_url": self.request.get_full_path(),
            "user_email": self.user.email,
        }
        if self.next_url:
            params["next_url"] = self.next_url

        return reverse("pro_connect:authorize", query=params)


class PreLoginView(LoginNotRequiredMixin, UserKindLoginMixin, FormView):
    """
    Generic login for all users:
    They enter their email and are redirected to the login method configured on their account.
    """

    template_name = "account/pre_login.html"
    form_class = FindExistingUserViaEmailForm

    @method_decorator(rate_limit(action="login"))
    def dispatch(self, request, *args, **kwargs):
        self.next_url = get_safe_url(request, REDIRECT_FIELD_NAME)
        if self.next_url:
            if get_url_param_value(self.next_url, "channel") == ProConnectChannel.MAP_CONSEILLER:
                query = {
                    "user_kind": UserKind.PRESCRIBER,
                    "next_url": self.next_url,
                    "channel": ProConnectChannel.MAP_CONSEILLER.value,
                }
                return HttpResponseRedirect(reverse("pro_connect:authorize", query=query))
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        self.user = form.user
        return super().form_valid(form)

    def get_success_url(self):
        if self.user.identity_provider == IdentityProvider.PRO_CONNECT:
            # Handle environments where ProConnect isn't plugged in
            if pro_connect_url := self._get_pro_connect_url():
                # We don't need to display the ProConnect button, skip it and just redirect to ProConnect
                return pro_connect_url
        params = {"back_url": self.request.get_full_path()}
        if self.next_url:
            params[REDIRECT_FIELD_NAME] = self.next_url
        self.request.session[ITOU_SESSION_LOGIN_EMAIL_KEY] = self.user.email
        return reverse("login:existing_user", query=params)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context | {"redirect_field_value": self.next_url}


class ExistingUserLoginView(LoginNotRequiredMixin, UserKindLoginMixin, LoginView):
    """
    Allows a user to login with the provider configured on their account.
    """

    template_name = "account/login_existing_user.html"
    form_class = ItouLoginForm

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.user = None
        if email := self.request.session.get(ITOU_SESSION_LOGIN_EMAIL_KEY):
            self.user = User.objects.filter(email=email).first()
        self.next_url = get_safe_url(self.request, REDIRECT_FIELD_NAME)

    def dispatch(self, request, *args, **kwargs):
        if self.user is None:
            return HttpResponseRedirect(reverse("account_login"))
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user_email"] = self.user.email
        return kwargs

    def form_valid(self, form):
        del self.request.session[ITOU_SESSION_LOGIN_EMAIL_KEY]
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        extra_context = {
            "back_url": get_safe_url(self.request, "back_url", reverse("account_login")),
            "matomo_account_type": MATOMO_ACCOUNT_TYPE[self.user.kind]
            if self.user.kind in MATOMO_ACCOUNT_TYPE
            else self.user.kind,
            "login_provider": self.user.identity_provider,
            "show_france_connect": bool(settings.FRANCE_CONNECT_BASE_URL),
            "show_peamu": bool(settings.PEAMU_AUTH_BASE_URL),
            "redirect_field_value": self.next_url,
            "pro_connect_url": self._get_pro_connect_url(),
            "uses_pro_connect": self.user.kind in [UserKind.PRESCRIBER, UserKind.EMPLOYER],
        }
        return context | extra_context

    def get_success_url(self):
        return self.next_url or super().get_success_url()


class VerifyOTPView(FormView):
    template_name = "account/verify_otp.html"
    form_class = VerifyOTPForm

    def get_form_kwargs(self):
        return super().get_form_kwargs() | {"user": self.request.user}

    def form_valid(self, form):
        otp_login(self.request, self.request.user.otp_device)
        return super().form_valid(form)

    def get_success_url(self):
        return get_safe_url(self.request, REDIRECT_FIELD_NAME, reverse("dashboard:index"))


@require_POST
@login_not_required
def demo_login_view(request):
    if settings.SHOW_DEMO_ACCOUNTS_BANNER:
        form = ItouLoginForm(request=request, data=request.POST)
        if form.is_valid() and form.cleaned_data.get("demo_banner_account"):
            form.login(request)
            return HttpResponseRedirect(reverse("dashboard:index"))

    raise Http404()
