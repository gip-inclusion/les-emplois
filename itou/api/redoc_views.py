from django.templatetags.static import static
from drf_spectacular.views import SpectacularRedocView


class ItouSpectacularRedocView(SpectacularRedocView):
    @staticmethod
    def _redoc_standalone():
        return static("vendor/redoc-2.0.0/redoc.standalone.js")
