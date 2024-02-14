from django.apps import AppConfig
from django.db import OperationalError, ProgrammingError, transaction
from django.db.models.signals import post_migrate


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "itou.communications"

    def ready(self):
        self.module.autodiscover()
        sync_notifications(self.get_model("Notification"))
        post_migrate.connect(post_communications_migrate_handler, sender=self)


def post_communications_migrate_handler(sender, app_config, **kwargs):
    sync_notifications(app_config.get_model("Notification"))


def sync_notifications(notification_model):
    from . import registry

    try:
        with transaction.atomic():
            with transaction.get_connection().cursor() as cursor:
                cursor.execute(f"LOCK TABLE {notification_model._meta.db_table};")

            # Add new notifications to database.
            active_notifications = []
            for notification_class in registry._registry:
                notification, created = notification_model.objects.update_or_create(
                    notification_class=notification_class.get_class_path(),
                    defaults={
                        "name": str(notification_class.name),
                        "category": str(notification_class.category),
                        "can_be_disabled": notification_class.can_be_disabled,
                        "is_obsolete": False,
                    },
                )
                active_notifications.append(notification)

            # Flag obsolete notifications
            notification_model.objects.exclude(
                pk__in=[notification.pk for notification in active_notifications]
            ).update(is_obsolete=True)
    except (OperationalError, ProgrammingError):
        # Ignore if database/table are not created yet
        pass
