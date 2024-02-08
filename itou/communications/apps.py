from django.apps import AppConfig
from django.conf import settings
from django.db import OperationalError, ProgrammingError, transaction
from django.db.models.signals import post_migrate


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "itou.communications"

    def ready(self):
        self.module.autodiscover()
        post_migrate.connect(post_communications_migrate_handler, sender=self)
        if settings.DEBUG:
            # Sync on every reload during development
            sync_notifications(self.get_model("NotificationRecord"))


def post_communications_migrate_handler(sender, app_config, **kwargs):
    sync_notifications(app_config.get_model("NotificationRecord"))


def sync_notifications(notification_record_model):
    from . import registry

    try:
        with transaction.atomic():
            with transaction.get_connection().cursor() as cursor:
                cursor.execute(f"LOCK TABLE {notification_record_model._meta.db_table};")

            # Add new notifications to database.
            active_notification_records = []
            for notification_class in registry:
                notification_record, created = notification_record_model.include_obsolete.update_or_create(
                    notification_class=notification_class.__name__,
                    defaults={
                        "name": notification_class.name,
                        "category": notification_class.category,
                        "can_be_disabled": notification_class.can_be_disabled,
                        "is_obsolete": False,
                    },
                )
                active_notification_records.append(notification_record)

            # Flag obsolete notifications
            notification_record_model.objects.exclude(
                pk__in=[notification_record.pk for notification_record in active_notification_records]
            ).update(is_obsolete=True)
    except (OperationalError, ProgrammingError):
        if settings.DEBUG:
            # Ignore if database/table are not created yet
            return
        raise
