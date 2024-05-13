from django.db import models
from django.utils import timezone

from itou.users.models import User


class FollowUpGroup(models.Model):
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    beneficiary = models.OneToOneField(
        User,
        verbose_name="bénéficiaire",
        null=False,
        blank=False,
        on_delete=models.RESTRICT,
        related_name="follow_up_group",
    )

    members = models.ManyToManyField(
        User,
        through="FollowUpGroupMembership",
        through_fields=("follow_up_group", "member"),
        related_name="follow_up_groups_member",
    )

    class Meta:
        verbose_name = "groupe de suivi"
        verbose_name_plural = "groupes de suivi"

    def __str__(self):
        return "Groupe de " + self.beneficiary.get_full_name()


class FollowUpGroupMembership(models.Model):
    is_referent = models.BooleanField(default=False, verbose_name="référent")

    # Is this user still an active member of the group?
    # Or maybe waiting for an invitation to be activated?
    is_active = models.BooleanField(default=True, verbose_name="actif")

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    # Keep track of when the membership was ended
    ended_at = models.DateTimeField(null=True)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    follow_up_group = models.ForeignKey(
        FollowUpGroup,
        verbose_name="groupe de suivi",
        related_name="memberships",
        on_delete=models.RESTRICT,
    )

    member = models.ForeignKey(
        User,
        verbose_name="membre du groupe de suivi",
        related_name="follow_up_groups",
        on_delete=models.RESTRICT,
    )

    # Keep track of who created this entry
    creator = models.ForeignKey(
        User,
        verbose_name="créateur",
        related_name="created_follow_up_groups",
        on_delete=models.RESTRICT,
    )

    def __str__(self):
        return self.follow_up_group.beneficiary.get_full_name() + " => " + self.member.get_full_name()
