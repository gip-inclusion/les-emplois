from django.apps import AppConfig


class ArchiveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "itou.pg_storage"
    verbose_name = "PostgreSQL Storage for Tasks Management"
