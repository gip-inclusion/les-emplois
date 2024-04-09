from django.db import models
from django.utils import timezone

from itou.users.models import JobSeekerProfile, User


class FollowUpGroupMembership(models.Model):

    follow_up_group_membership_id = models.AutoField(primary_key=True)

    is_referent = models.BooleanField(default=False)

    # Is this user still an active member of the group?
    is_active_member = models.BooleanField(default=True)

    # Keep track of when the membership was ended
    membership_ended_at = models.DateTimeField(null=True)

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    jobseeker = models.ForeignKey(
        JobSeekerProfile,
        verbose_name="candidat",
        related_name="follow_up_group",
        null=False,
        blank=False,
        on_delete=models.RESTRICT,
        unique=True,
    )

    member = models.ForeignKey(
        User,
        verbose_name="membre du groupe de suivi",
        related_name="follow_up_groups",
        null=False,
        blank=False,
        on_delete=models.RESTRICT,
    )

    # Keep track of who created this entry
    creator = models.ForeignKey(
        User,
        verbose_name="créateur",
        related_name="created_follow_up_groups",
        null=False,
        blank=False,
        on_delete=models.RESTRICT,
    )

    class Meta:
        db_table = "gps_follow_up_group_membership"
        verbose_name = "groupe de suivi"
        verbose_name_plural = "groupes de suivi"
        unique_together = (("jobseeker", "member"),)
