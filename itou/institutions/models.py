"""
Institutions are stakeholder groups who are neither SIAE nor Prescriber Organizations.
They share some features with SIAE and Prescriber Organization objects,
such as memberships, administrators rights or the Address mixin.
The first member is imported from a CSV file. Joining an institution is possible only with
an invitation from one of its members.

For the moment, only labor inspectors (User.is_labor_inspector) can be members.
They belong to a DDETS, a DREETS or a DGEFP.
"""

from django.conf import settings
from django.db import models

from itou.common_apps.address.models import AddressMixin
from itou.common_apps.organizations.models import MembershipAbstract, OrganizationAbstract, OrganizationQuerySet
from itou.institutions.enums import InstitutionKind


class Institution(AddressMixin, OrganizationAbstract):
    class Meta:
        verbose_name = "Institution partenaire"
        verbose_name_plural = "Institutions partenaires"

    kind = models.CharField(
        verbose_name="Type", max_length=20, choices=InstitutionKind.choices, default=InstitutionKind.OTHER
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
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
        settings.AUTH_USER_MODEL,
        related_name="updated_institutionmembership_set",
        null=True,
        on_delete=models.CASCADE,
        verbose_name="Mis à jour par",
    )

    class Meta:
        unique_together = ("user_id", "institution_id")
