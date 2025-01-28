from django.shortcuts import redirect
from django.views.generic import TemplateView

from itou.utils.auth import get_logout_redirect_url
from itou.utils.views import NextRedirectMixin, logout_with_message
from itou.www.logout.enums import LogoutWarning


class LogoutView(NextRedirectMixin, TemplateView):
    template_name = "account/logout.html"

    def get(self, *args, **kwargs):
        # NOTE: view doesn't logout on GET
        if not self.request.user.is_authenticated:
            return redirect(self.get_redirect_url())
        return self.render_to_response(self.get_context_data())

    def post(self, *args, **kwargs):
        url = self.get_redirect_url()
        if self.request.user.is_authenticated:
            logout_with_message(self.request)
        return redirect(url)

    def get_redirect_url(self):
        return self.get_next_url() or get_logout_redirect_url(self.request)


class LogoutWarningView(TemplateView):
    """
    Logout view used when the perms middleware detects an issue
    """

    template_name = "logout/warning.html"

    def dispatch(self, request, kind):
        self.kind = kind
        if self.kind not in LogoutWarning:
            return redirect("accounts:account_logout")
        return super().dispatch(request, kind)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context | {
            "LogoutWarning": LogoutWarning,
            "warning": self.kind,
        }
