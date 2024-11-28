from django.templatetags.static import static
from drf_spectacular.views import SpectacularRedocView

from itou.utils.auth import LoginNotRequiredMixin


class ItouSpectacularRedocView(LoginNotRequiredMixin, SpectacularRedocView):
    @staticmethod
    def _redoc_standalone():
        return static("vendor/redoc/redoc.standalone.js")
