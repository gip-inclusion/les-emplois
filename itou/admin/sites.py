from django.contrib.admin import sites as admin_sites


class AdminSite(admin_sites.AdminSite):
    site_header = "Admin Itou"
    site_title = "Les emplois de l'inclusion"
