import functools

from django.conf import settings
from django.http import Http404
from django.urls import reverse
from django.views.generic import TemplateView
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView

from itou.api.documentation import DOCUMENTATIONS, DocumentationSchemaGenerator
from itou.utils.auth import LoginNotRequiredMixin


def get_documentation_or_404(slug):
    try:
        return DOCUMENTATIONS[slug]
    except KeyError:
        raise Http404("Documentation inconnue")


class DocumentationSchemaView(LoginNotRequiredMixin, SpectacularAPIView):
    """OpenAPI schema restricted to the endpoints of a single documentation."""

    # Overriding `get` drops the `extend_schema` decoration of SpectacularAPIView.get,
    # and documenting the schema endpoint in the schema itself is of no use to API users.
    @extend_schema(exclude=True)
    def get(self, request, *args, slug, **kwargs):
        self.generator_class = functools.partial(
            DocumentationSchemaGenerator, documentation=get_documentation_or_404(slug)
        )
        return super().get(request, *args, **kwargs)


class ScalarView(LoginNotRequiredMixin, TemplateView):
    """API reference rendered by Scalar (https://github.com/scalar/scalar) from the OpenAPI schema."""

    template_name = "api/scalar.html"

    def get_context_data(self, *, slug, **kwargs):
        documentation = get_documentation_or_404(slug)
        return super().get_context_data(**kwargs) | {
            "title": f"{documentation.title} - {settings.SPECTACULAR_SETTINGS['TITLE']}",
            # https://scalar.com/products/api-references/configuration
            "scalar_configuration": {
                "url": reverse("v1:documentation_schema", kwargs={"slug": documentation.slug}),
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
