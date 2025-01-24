from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import ImproperlyConfigured
from django.utils.html import format_html

from itou.utils.requests import get_next_redirect_url, get_request_param, passthrough_next_redirect_url


class NextRedirectMixin:
    redirect_field_name = REDIRECT_FIELD_NAME

    def get_context_data(self, **kwargs):
        ret = super().get_context_data(**kwargs)
        redirect_field_value = get_request_param(self.request, self.redirect_field_name)
        ret.update(
            {
                "redirect_field_name": self.redirect_field_name,
                "redirect_field_value": redirect_field_value,
                "redirect_field": (
                    format_html(
                        '<input type="hidden" name="{}" value="{}">',
                        self.redirect_field_name,
                        redirect_field_value,
                    )
                    if redirect_field_value
                    else ""
                ),
            }
        )
        return ret

    def get_success_url(self):
        """
        We're in a mixin, so we cannot rely on the fact that our super() has a get_success_url.
        Also, we want to check for -- in this order:
        1) The `?next=/foo`
        2) The `get_succes_url()` if available.
        3) The `.success_url` if available.
        4) A fallback default success URL: `get_default_success_url()`.
        """
        url = self.get_next_url()
        if url:
            return url

        if not url:
            if hasattr(super(), "get_success_url"):
                try:
                    url = super().get_success_url()
                except ImproperlyConfigured:
                    # Django's default get_success_url() checks self.succes_url,
                    # and throws this if that is not set. Yet, in our case, we
                    # want to fallback to the default.
                    pass
            elif hasattr(self, "success_url"):
                url = self.success_url
                if url:
                    url = str(url)  # reverse_lazy
        if not url:
            url = self.get_default_success_url()
        return url

    def get_default_success_url(self):
        return None

    def get_next_url(self):
        return get_next_redirect_url(self.request, self.redirect_field_name)

    def passthrough_next_url(self, url):
        return passthrough_next_redirect_url(self.request, url, self.redirect_field_name)
