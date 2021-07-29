from django.conf import settings
from django.db import models
from django.utils import timezone


class MembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, user__is_active=True)


class MembershipAbstract(models.Model):
    """
    Abstract class to handle memberships.
    Inherit from it to create an intermediary model between `User` and another model.
    Example: itou.prescribers.models.PrescriberMembership

    The child model should implement the following elements:
    ```
    related_model = models.ForeignKey(MyModel, on_delete=models.CASCADE)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_membershipmodel_set",
        null=True,
        on_delete=models.CASCADE,
        verbose_name="Mis à jour par",
    )

    class Meta:
        unique_together = ("user_id", "related_model_id")
    ```
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(verbose_name="Date d'adhésion", default=timezone.now)
    is_admin = models.BooleanField(verbose_name="Administrateur", default=False)
    is_active = models.BooleanField("Rattachement actif", default=True)
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", null=True)

    objects = models.Manager.from_queryset(MembershipQuerySet)()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    def deactivate_membership_by_user(self, user):
        """
        Deactivates the membership of a member (reference held by self)
        `user` is the admin updating this user (`updated_by` field)
        """
        self.is_active = False
        self.updated_by = user
        return True

    def set_admin_role(self, active, user):
        """
        Set admin role for the given user.
        `user` is the admin updating this user (`updated_by` field)
        """
        self.is_admin = active
        self.updated_by = user
