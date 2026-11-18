from django.apps import AppConfig


class NextStepsConfig(AppConfig):
    """The data of the « Prochaines étapes » experiment (its views are in itou.www.next_steps_views)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "itou.next_steps"
    verbose_name = "Prochaines étapes"
