from django.contrib.admin import sites as admin_sites
from django.urls import path

from itou.admin import views


class AdminSite(admin_sites.AdminSite):
    site_header = "Admin Itou"
    site_title = "Les emplois de l'inclusion"

    def get_urls(self):
        base_urlpatterns = super().get_urls()

        extra_urlpatterns = [
            path("confirm-otp/", self.admin_view(views.AdminConfirmOTPAuthView.as_view()), name="confirm_otp"),
        ]

        return extra_urlpatterns + base_urlpatterns
