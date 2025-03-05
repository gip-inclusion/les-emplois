from django.contrib.admin import sites as admin_sites
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import login_not_required
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from itou.admin import views
from itou.users.models import User


class AdminSite(admin_sites.AdminSite):
    site_header = "Admin Itou"
    site_title = "Les emplois de l'inclusion"

    def get_urls(self):
        base_urlpatterns = super().get_urls()

        extra_urlpatterns = [
            path("confirm-otp/", self.admin_view(views.AdminConfirmOTPAuthView.as_view()), name="confirm_otp"),
        ]

        return extra_urlpatterns + base_urlpatterns

    @method_decorator(never_cache)
    @login_not_required
    def login(self, request, *args, **kwargs):
        if request.method != "POST":
            return super().login(request, *args, **kwargs)

        username = request.POST.get("username")
        user = User.objects.filter(email=username).first()
        if user.otp_secret:
            request.POST._mutable = True
            request.POST[REDIRECT_FIELD_NAME] = reverse("admin:confirm_otp")

        request.POST._mutable = False

        return super().login(request, *args, **kwargs)
