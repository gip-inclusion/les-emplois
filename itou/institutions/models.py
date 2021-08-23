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

from itou.users.models import User
from itou.utils.organizations.models import MembershipAbstract, OrganizationAbstract, OrganizationQuerySet


class Institution(OrganizationAbstract):
    class Kind(models.TextChoices):
        DDETS = ("DDETS", "Direction départementale de l'emploi, du travail et des solidarités")
        DREETS = ("DREETS", "Direction régionale de l'économie, de l'emploi, du travail et des solidarités")
        DGEFP = ("DGEFP", "Délégation générale à l'emploi et à la formation professionnelle")
        OTHER = "OTHER", "Autre"

    class Meta:
        verbose_name = "Institution partenaire"
        verbose_name_plural = "Institutions partenaires"

    kind = models.CharField(verbose_name="Type", max_length=20, choices=Kind.choices, default=Kind.OTHER)
    members = models.ManyToManyField(
        User,
        verbose_name="Membres",
        through="InstitutionMembership",
        blank=True,
        through_fields=("institution", "user"),
    )

    objects = models.Manager.from_queryset(OrganizationQuerySet)()


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
