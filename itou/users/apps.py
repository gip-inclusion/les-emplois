from django.apps import AppConfig
from django.contrib.auth.signals import user_logged_in


class UsersAppConfig(AppConfig):
    name = "itou.users"
    verbose_name = "Utilisateurs"

    def ready(self):
        from django.contrib.auth.models import update_last_login

        from .models import update_first_login

        # Already done in django.contrib.auth.AuthConfig, but since we need it before update_first_login
        # better connect it again here just in case (it won't be called twice)
        user_logged_in.connect(update_last_login, dispatch_uid="update_last_login")
        user_logged_in.connect(update_first_login, dispatch_uid="update_first_login")
