from django.apps import AppConfig


# For custom app config, see:
# https://docs.djangoproject.com/en/3.0/ref/applications/#for-application-authors


class ExternalDataConfig(AppConfig):
    name = "itou.external_data"

    def ready(self):
        """
        When the app is loaded:
        import / activate registration to allauth login signals
        """
        from . import signals
