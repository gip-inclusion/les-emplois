"""
Institutions are stakeholder groups who are neither SIAE nor Prescriber Organizations.
They share some features with SIAE and Prescriber Organization objects,
such as memberships, administrators rights or the Address mixin.
The first member is imported from a CSV file. Joining an institution is possible only with
an invitation from one of its members.

For the moment, only labor inspectors (User.is_labor_inspector) can be members.
They belong to a DDETS, a DREETS or a DGEFP.
"""

from django.db import models
from django.db.models import Prefetch
from django.utils import timezone

from itou.users.models import User
from itou.utils.address.models import AddressMixin
from itou.utils.emails import get_email_message
from itou.utils.structures.models import MembershipAbstract, StructureQuerySet


class Institution(AddressMixin):
    class Kind(models.TextChoices):
        DDETS = ("DDETS", "Direction départementale de l'emploi, du travail et des solidarités")
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

    objects = models.Manager.from_queryset(StructureQuerySet)()

    def __str__(self):
        return f"{self.name}"

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    def has_admin(self, user):
        return self.active_admin_members.filter(pk=user.pk).exists()

    @property
    def has_members(self):
        return self.active_members.exists()

    @property
    def display_name(self):
        # Keep same logic as SIAE and PrescriberOrganization.
        return self.name

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

    @property
    def deactivated_members(self):
        """
        List of previous members of the structure, still active as user (from the model POV)
        but deactivated by an admin at some point in time.

        Query will be optimized later with Qs.
        """
        return self.members.filter(is_active=True, institutionmembership__is_active=False)

    # E-mails
    def member_deactivation_email(self, user):
        """
        Send email when an admin of the structure disables the membership of a given user (deactivation).
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/member_deactivation_email_subject.txt"
        body = "common/emails/member_deactivation_email_body.txt"
        return get_email_message(to, context, subject, body)

    def add_admin_email(self, user):
        """
        Send info email to a new admin of the organization (added)
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/add_admin_email_subject.txt"
        body = "common/emails/add_admin_email_body.txt"
        return get_email_message(to, context, subject, body)

    def remove_admin_email(self, user):
        """
        Send info email to a former admin of the organization (removed)
        """
        to = [user.email]
        context = {"structure": self}
        subject = "common/emails/remove_admin_email_subject.txt"
        body = "common/emails/remove_admin_email_body.txt"
        return get_email_message(to, context, subject, body)


class InstitutionMembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, user__is_active=True)


class InstitutionMembership(MembershipAbstract):
    """Intermediary model between `User` and `Institution`."""

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE)
    updated_by = models.ForeignKey(
        User,
        related_name="updated_institutionmembership_set",
        null=True,
        on_delete=models.CASCADE,
        verbose_name="Mis à jour par",
    )

    class Meta:
        unique_together = ("user_id", "institution_id")
