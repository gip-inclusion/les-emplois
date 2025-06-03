from django.apps import AppConfig


class ArchiveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "itou.archive"
    verbose_name = "Archives anonymisées"
