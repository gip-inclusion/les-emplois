from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class NotificationRecordQuerySet(models.QuerySet):
    def actives(self):
        return self.exclude(is_obsolete=True)


class NotificationRecordManager(models.Manager.from_queryset(NotificationRecordQuerySet)):
    def get_queryset(self):
        return super().get_queryset().actives()


class NotificationRecord(models.Model):
    notification_class = models.CharField(unique=True)
    name = models.CharField()
    category = models.CharField()
    can_be_disabled = models.BooleanField()
    is_obsolete = models.BooleanField(default=False, db_index=True)

    objects = NotificationRecordManager()
    include_obsolete = NotificationRecordQuerySet.as_manager()

    class Meta:
        base_manager_name = "include_obsolete"
        ordering = ["category", "name"]
        constraints = [
            models.CheckConstraint(
                name="notificationrecord_category_and_name_required",
                check=~(models.Q(category="") | models.Q(name="")),
            ),
        ]

    def __str__(self):
        return self.name


class DisabledNotification(models.Model):
    notification_record = models.ForeignKey("NotificationRecord", on_delete=models.CASCADE)
    settings = models.ForeignKey("NotificationSettings", on_delete=models.CASCADE)
    disabled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint("notification_record", "settings", name="unique_notificationrecord_per_settings"),
        ]


class NotificationSettingsQuerySet(models.QuerySet):
    def for_structure(self, structure=None):
        qs = self.prefetch_related("disabled_notifications")
        if structure is None:
            return qs.filter(structure_type=None, structure_pk=None)
        return qs.filter(structure_type=ContentType.objects.get_for_model(structure), structure_pk=structure.pk)


class NotificationSettings(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_settings")
    structure_type = models.ForeignKey(ContentType, null=True, on_delete=models.CASCADE)
    structure_pk = models.PositiveIntegerField(null=True)
    structure = GenericForeignKey("structure_type", "structure_pk")
    disabled_notifications = models.ManyToManyField(NotificationRecord, through=DisabledNotification, related_name="+")

    objects = NotificationSettingsQuerySet.as_manager()

    class Meta:
        base_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                "user",
                condition=models.Q(structure_pk__isnull=True),
                name="unique_settings_per_individual_user",
            ),
            models.UniqueConstraint(
                "user",
                "structure_type",
                "structure_pk",
                condition=models.Q(structure_pk__isnull=False),
                name="unique_settings_per_organizational_user",
            ),
        ]

    def __str__(self):
        if self.structure:
            return f"Paramètres de notification de {self.user.get_full_name()} ({self.structure})"
        return f"Paramètres de notification de {self.user.get_full_name()}"

    @staticmethod
    def get_or_create(user, structure=None):
        if structure is None:
            structure_type = None
            structure_pk = None
        else:
            structure_type = ContentType.objects.get_for_model(structure)
            structure_pk = structure.pk

        notification_settings, created = NotificationSettings.objects.get_or_create(
            user=user,
            structure_type=structure_type,
            structure_pk=structure_pk,
        )
        return notification_settings, created
