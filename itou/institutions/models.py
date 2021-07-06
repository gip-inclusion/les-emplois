from django.db import models
from django.utils import timezone

from itou.users.models import User
from itou.utils.address.models import AddressMixin


class Institution(AddressMixin):
    """
    TODO
    """

    class Kind(models.TextChoices):
        DDEETS = ("DDEETS", "Direction départementale de l'économie, de l'emploi, du travail et des solidarités")
        DREETS = ("DREETS", "Direction régionale de l'économie, de l'emploi, du travail et des solidarités")
        DGEFP = ("DGEFP", "Délégation générale à l'emploi et à la formation professionnelle")
        OTHER = "OTHER", "Autre"

    class Meta:
        verbose_name = "Institution partenaire"
        verbose_name_plural = "Institutions partenaires"

    kind = models.CharField(verbose_name="Type", max_length=20, choices=Kind.choices, default=Kind.OTHER)
    name = models.CharField(verbose_name="Nom", max_length=255)
    members = models.ManyToManyField(
        User,
        verbose_name="Membres",
        through="InstitutionMembership",
        blank=True,
        through_fields=("institution", "user"),
    )
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True)

    def __str__(self):
        return f"{self.name}"

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @property
    def active_members(self):
        """
        In this context, active == has an active membership AND user is still active.

        Query will be optimized later with Qs.
        """
        return self.members.filter(is_active=True, institutionmembership__is_active=True)

    @property
    def active_admin_members(self):
        """
        Active admin members:
        active user/admin in this context means both:
        * user.is_active: user is able to do something on the platform
        * user.membership.is_active: is a member of this structure

        Query will be optimized later with Qs.
        """
        return self.members.filter(
            is_active=True, institutionmembership__is_admin=True, institutionmembership__is_active=True
        )


class InstitutionMembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, user__is_active=True)


class InstitutionMembership(models.Model):
    """Intermediary model between `User` and `Institution`."""

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE)
    is_admin = models.BooleanField(verbose_name="Administrateur", default=False)
    is_active = models.BooleanField("Rattachement actif", default=True)
    joined_at = models.DateTimeField(verbose_name="Date d'adhésion", default=timezone.now)
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="Date de modification", null=True)

    objects = models.Manager.from_queryset(InstitutionMembershipQuerySet)()

    class Meta:
        unique_together = ("user_id", "institution_id")

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)
