from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from itou.companies.models import Company
from itou.institutions.models import Institution
from itou.prescribers.models import PrescriberOrganization
from itou.users.notifications import OrganizationActiveMembersReminderNotification
from itou.utils.command import BaseCommand
from itou.utils.urls import get_absolute_url


class Command(BaseCommand):
    """
    Send an email reminder every 3 months asking admins of companies, organizations and institutions
    having more than 1 member to review members access and ensure that only authorized members have
    access to the organization data.
    """

    def build_query(self, queryset):
        TODAY = timezone.localdate()

        return (
            queryset.prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=queryset.model.members.through.objects.order_by("pk")
                    .active()
                    .admin()
                    .select_related("user"),
                    to_attr="admin_memberships",
                )
            )
            .annotate(
                last_sent_at=Coalesce("active_members_email_reminder_last_sent_at", "created_at"),
                active_members_count=Count(
                    "members",
                    filter=Q(
                        memberships__is_active=True,
                        memberships__user__is_active=True,
                    ),
                ),
            )
            .filter(
                last_sent_at__date__lte=TODAY - relativedelta(months=3),
                active_members_count__gt=1,
            )
            .order_by("pk")
        )

    def handle(self, *args, **options):
        NOW = timezone.now()

        # Companies
        companies = self.build_query(Company.objects.active())
        companies_members_url = get_absolute_url(reverse("companies_views:members"))
        self.logger.info("Processing %d companies", len(companies))
        for company in companies:
            with transaction.atomic():
                for membership in company.admin_memberships:
                    OrganizationActiveMembersReminderNotification(
                        membership.user,
                        company,
                        active_admins_count=len(company.admin_memberships),
                        members_url=companies_members_url,
                    ).send()
                    self.logger.info(
                        "Sent reminder notification to user %d for company %d",
                        membership.user.pk,
                        company.pk,
                    )
                company.active_members_email_reminder_last_sent_at = NOW
                company.save(update_fields=["active_members_email_reminder_last_sent_at", "updated_at"])

        # Prescriber organizations
        prescriber_organizations = self.build_query(PrescriberOrganization.objects.all())
        prescriber_organizations_members_url = get_absolute_url(reverse("prescribers_views:members"))
        self.logger.info("Processing %d prescriber organizations", len(prescriber_organizations))
        for prescriber_organization in prescriber_organizations:
            with transaction.atomic():
                for membership in prescriber_organization.admin_memberships:
                    OrganizationActiveMembersReminderNotification(
                        membership.user,
                        prescriber_organization,
                        active_admins_count=len(prescriber_organization.admin_memberships),
                        members_url=prescriber_organizations_members_url,
                    ).send()
                    self.logger.info(
                        "Sent reminder notification to user %d for prescriber organization %d",
                        membership.user.pk,
                        prescriber_organization.pk,
                    )
                prescriber_organization.active_members_email_reminder_last_sent_at = NOW
                prescriber_organization.save(
                    update_fields=["active_members_email_reminder_last_sent_at", "updated_at"]
                )

        # Institutions
        institutions = self.build_query(Institution.objects.all())
        institutions_members_url = get_absolute_url(reverse("institutions_views:members"))
        self.logger.info("Processing %d institutions", len(institutions))
        for institution in institutions:
            with transaction.atomic():
                for membership in institution.admin_memberships:
                    OrganizationActiveMembersReminderNotification(
                        membership.user,
                        institution,
                        active_admins_count=len(institution.admin_memberships),
                        members_url=institutions_members_url,
                    ).send()
                    self.logger.info(
                        "Sent reminder notification to user %d for institution %d", membership.user.pk, institution.pk
                    )
                institution.active_members_email_reminder_last_sent_at = NOW
                institution.save(update_fields=["active_members_email_reminder_last_sent_at", "updated_at"])
