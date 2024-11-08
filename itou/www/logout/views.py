from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

from itou.www.logout.enums import LogoutWarning


class LogoutWarningView(LoginRequiredMixin, TemplateView):
    """
    Logout view used when the perms middleware detects an issue
    """

    template_name = "logout/warning.html"

    def dispatch(self, request, kind):
        self.kind = kind
        if self.kind not in LogoutWarning:
            return redirect("account_logout")
        return super().dispatch(request, kind)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context | {
            "LogoutWarning": LogoutWarning,
            "warning": self.kind,
        }
