from django.contrib.admin import apps as admin_apps


class AdminConfig(admin_apps.AdminConfig):
    default_site = "itou.admin.sites.AdminSite"
