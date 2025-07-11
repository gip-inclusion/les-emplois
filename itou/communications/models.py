import calendar
from datetime import date

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.core.files.storage import storages
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from itou.files.models import File
from itou.users.enums import UserKind


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
                condition=~(models.Q(category="") | models.Q(name="")),
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

    @property
    def disabled_notifications_names(self):
        return self.disabled_notifications.actives().values_list("name", flat=True)


class AnnouncementCampaign(models.Model):
    """
    It is possible on the website to launch announcement content for a limited time period,
    intended for displaying the new features of the site to returning visitors
    """

    max_items = models.PositiveIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name="nombre d'articles affiché",
    )
    start_date = models.DateField(
        null=False,
        unique=True,
        verbose_name="mois concerné",
        help_text="le mois des nouveautés. Automatiquement fixé au premier du mois saisi",
    )
    live = models.BooleanField(
        default=True,
        verbose_name="prêt",
        help_text="les modifications sont toujours possible",
    )

    class Meta:
        verbose_name = "campagne d'annonce"
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(name="max_items_range", condition=Q(max_items__gte=1, max_items__lte=10)),
            models.CheckConstraint(name="start_on_month", condition=Q(start_date__day=1)),
        ]

    @property
    def end_date(self):
        """:return: the last day of the month targeted"""
        return date(
            self.start_date.year,
            self.start_date.month,
            calendar.monthrange(self.start_date.year, self.start_date.month)[1],
        )

    def __str__(self):
        return f"Campagne d'annonce du {self.start_date.strftime('%m/%Y')}"

    def clean(self):
        if self.start_date:
            self.start_date = self.start_date.replace(day=1)
        return super().clean()

    def _update_cached_active_announcement(self):
        from itou.communications.cache import get_cached_active_announcement, update_active_announcement_cache

        campaign = get_cached_active_announcement()
        if campaign is None or self.pk == campaign.pk:
            update_active_announcement_cache()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._update_cached_active_announcement()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._update_cached_active_announcement()

    def items_for_template(self, user_kind):
        return [
            item
            for item in self.items.all()
            # Only filter items for job seekers
            if not item.user_kind_tags or user_kind != UserKind.JOB_SEEKER or user_kind in item.user_kind_tags
        ][: self.max_items]


class AnnouncementItemQuerySet(models.QuerySet):
    def get_queryset(self):
        return super().get_queryset().select_related("campaign")


class AnnouncementItem(models.Model):
    campaign = models.ForeignKey(
        AnnouncementCampaign, on_delete=models.CASCADE, related_name="items", verbose_name="campagne"
    )
    priority = models.PositiveIntegerField(
        default=0, verbose_name="priorité", help_text="le plus bas le valeur, le plus haut dans le fil des articles"
    )
    title = models.TextField(null=False, blank=False, verbose_name="titre", help_text="résumé de nouveauté")
    description = models.TextField(
        null=False, blank=False, verbose_name="description", help_text="détail du nouveauté ; le contenu"
    )
    user_kind_tags = ArrayField(
        default=list,
        base_field=models.CharField(choices=UserKind.choices),
        verbose_name="utilisateurs concernés",
    )
    image = models.ImageField(
        blank=True,
        upload_to="news-images/",
        storage=storages["public"],
        verbose_name="capture d'écran",
        help_text="1200x600 recommandé",
        height_field="image_height",
        width_field="image_width",
    )
    # Denormalized information of image dimensions to avoid the need to access S3
    image_height = models.PositiveIntegerField(verbose_name="hauteur de l’image", null=True)
    image_width = models.PositiveIntegerField(verbose_name="largeur de l’image", null=True)
    image_alt_text = models.TextField(
        blank=True,
        verbose_name="description de l'image",
        help_text=(
            "la description est importante pour les utilisateurs de lecteurs d'écran,"
            " et lorsque l'image ne se télécharge pas"
        ),
    )
    image_storage = models.OneToOneField(
        File,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    link = models.URLField(
        blank=True,
        max_length=200,
        verbose_name="lien externe",
        help_text="URL d'une page où l'utilisateur peut obtenir plus d'informations sur l'article",
    )

    objects = AnnouncementItemQuerySet.as_manager()

    class Meta:
        verbose_name = "article d'annonce"
        ordering = ["-campaign__start_date", "priority", "pk"]
        unique_together = [("campaign", "priority")]

    def __str__(self):
        return self.title

    def _update_cached_active_announcement(self):
        from itou.communications.cache import get_cached_active_announcement, update_active_announcement_cache

        campaign = get_cached_active_announcement()
        if campaign is None or self.campaign == campaign:
            update_active_announcement_cache()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._update_cached_active_announcement()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._update_cached_active_announcement()

    @property
    def user_kind_labels(self):
        return [UserKind(u).label for u in self.user_kind_tags]
