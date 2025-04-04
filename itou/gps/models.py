import logging

from django.contrib.postgres.aggregates import ArrayAgg
from django.db import models, transaction
from django.utils import timezone

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.templatetags.str_filters import pluralizefr
from itou.www.gps.enums import EndReason


logger = logging.getLogger(__name__)


class BulkCreatedAtQuerysetProxy:
    def bulk_created(self):
        return self.filter(created_in_bulk=True)

    def not_bulk_created(self):
        return self.exclude(created_in_bulk=True)


class FollowUpGroupManager(models.Manager):
    def follow_beneficiary(self, beneficiary, user, is_referent=None, is_active=True):
        assert beneficiary.is_job_seeker
        if user.kind not in [UserKind.PRESCRIBER, UserKind.EMPLOYER]:
            # This should not happen but we don't want to block everything
            logger.warning("We should not try to add a FollowUpGroupMembership on user=%s", user)
            return
        now = timezone.now()
        with transaction.atomic():
            group, _ = FollowUpGroup.objects.get_or_create(beneficiary=beneficiary)

            update_args = {
                "ended_at": None,
                "end_reason": None,
                "last_contact_at": now,
                "is_active": is_active,
            }
            if is_referent is not None:
                update_args["is_referent"] = is_referent

            create_args = update_args | {
                "creator": user,
                "created_at": now,
                "started_at": timezone.localdate(),
            }

            membership, created = FollowUpGroupMembership.objects.update_or_create(
                follow_up_group=group,
                member=user,
                defaults=update_args,
                create_defaults=create_args,
            )
            return membership, created


class FollowUpGroupQueryset(BulkCreatedAtQuerysetProxy, models.QuerySet):
    pass


class FollowUpGroup(models.Model):
    """
    A group of stakeholders supporting the beneficiary
    """

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    created_in_bulk = models.BooleanField(verbose_name="créé massivement", default=False, db_index=True)

    objects = FollowUpGroupManager.from_queryset(FollowUpGroupQueryset)()

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


class FollowUpGroupMembershipQueryset(BulkCreatedAtQuerysetProxy, models.QuerySet):
    def with_members_organizations_names(self):
        qs = self.annotate(
            prescriber_org_names=ArrayAgg(
                "member__prescribermembership__organization__name",
                ordering=("-member__prescribermembership__is_admin", "member__prescribermembership__joined_at"),
            )
        ).annotate(
            companies_names=ArrayAgg(
                "member__companymembership__company__name",
                ordering=("-member__companymembership__is_admin", "member__companymembership__joined_at"),
            )
        )

        return qs


class FollowUpGroupMembership(models.Model):
    class Meta:
        verbose_name = "relation"
        constraints = [
            models.CheckConstraint(
                name="end_coherence",
                violation_error_message="Incohérence du champ motif de fin",
                condition=(
                    models.Q(ended_at=None, end_reason=None)
                    | models.Q(ended_at__isnull=False, end_reason__isnull=False)
                ),
            ),
        ]

    is_referent = models.BooleanField(default=False, verbose_name="référent")
    is_referent_certified = models.BooleanField(db_default=False, verbose_name="référent certifié")

    # Is this user still an active member of the group?
    # Or maybe waiting for an invitation to be activated?
    is_active = models.BooleanField(default=True, verbose_name="actif")

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    created_in_bulk = models.BooleanField(verbose_name="créé massivement", default=False, db_index=True)

    last_contact_at = models.DateTimeField(verbose_name="date de dernier contact", default=timezone.now)

    # date used by user to tell when they were following the user
    started_at = models.DateField(verbose_name="date de début de suivi")
    ended_at = models.DateField(verbose_name="date de fin de suivi", null=True, blank=True)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)
    # For user without proper access, this field allow to see personal informations in gps views
    can_view_personal_information = models.BooleanField(
        verbose_name="accès aux données du bénéficiaire", default=False
    )

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

    reason = models.TextField(blank=True, verbose_name="motif de suivi")
    end_reason = models.CharField(
        verbose_name="motif de fin",
        max_length=30,
        null=True,
        blank=True,
        choices=EndReason.choices,
    )

    objects = FollowUpGroupMembershipQueryset.as_manager()

    def __str__(self):
        return self.follow_up_group.beneficiary.get_full_name() + " => " + self.member.get_full_name()

    @property
    def organization_name(self):
        return next((name for name in (*self.prescriber_org_names, *self.companies_names) if name), None)

    @property
    def human_readable_followed_for(self):
        now = timezone.now()
        d = self.started_at
        # Get years and months (from django.utils.timesince.timesince)
        total_months = (now.year - d.year) * 12 + (now.month - d.month)
        if d.day > now.day:
            total_months -= 1

        if total_months == 0:
            return "moins d’un mois"

        years, months = divmod(total_months, 12)
        res = []
        if years:
            res.append(f"{years} an{pluralizefr(years)}")
        if months:
            res.append(f"{months} mois")
        return ", ".join(res)
