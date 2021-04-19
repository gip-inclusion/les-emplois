from django.apps import AppConfig


# For custom app config, see:
# https://docs.djangoproject.com/en/3.0/ref/applications/#for-application-authors


class ExternalDataConfig(AppConfig):
    name = "itou.external_data"
    verbose_name = "Gestion des données utilisateur (APIs externes)"

    def ready(self):
        """
        When the app is loaded:
        import / activate registration to allauth login signals
        """
        import itou.external_data.signals  # noqa F401
