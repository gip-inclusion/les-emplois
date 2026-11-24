from django.conf import settings
from django.urls import reverse
from django.views.generic import TemplateView

from itou.utils.auth import LoginNotRequiredMixin


class ScalarView(LoginNotRequiredMixin, TemplateView):
    """API reference rendered by Scalar (https://github.com/scalar/scalar) from the OpenAPI schema."""

    template_name = "api/scalar.html"
    url_name = "v1:openapi_schema"

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "title": settings.SPECTACULAR_SETTINGS["TITLE"],
            # https://scalar.com/products/api-references/configuration
            "scalar_configuration": {
                "url": reverse(self.url_name),
                # Fonts would be loaded from fonts.scalar.com.
                "withDefaultFonts": False,
                "telemetry": False,
                # Both are enabled by default on localhost.
                "showDeveloperTools": "never",
                "agent": {"disabled": True},
                # Hide the "Open API Client" button.
                "hideClientButton": True,
                "localization": {
                    "locale": "fr",
                },
            },
        }
