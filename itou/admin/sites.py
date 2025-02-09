from django.contrib.admin import sites as admin_sites


class AdminSite(admin_sites.AdminSite):
    site_header = "Admin Itou"
