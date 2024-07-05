from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from itou.companies.models import Company
from itou.institutions.models import Institution
from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User
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
        membership_attname = queryset.model.members.through._meta.get_field("user").remote_field.name

        return (
            queryset.prefetch_related(
                Prefetch(
                    "members",
                    queryset=User.objects.order_by("pk").filter(
                        Exists(
                            queryset.model.members.through.objects.filter(
                                user=OuterRef("pk"), is_active=True, is_admin=True
                            )
                        ),
                        is_active=True,
                    ),
                    to_attr="admin_members",
                )
            )
            .annotate(
                last_sent_at=Coalesce("active_members_email_reminder_last_sent_at", "created_at"),
                active_members_count=Count(
                    "members",
                    filter=Q(
                        **{
                            f"{membership_attname}__is_active": True,
                            f"{membership_attname}__user__is_active": True,
                        }
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
        self.stdout.write(f"Processing {len(companies)} companies")
        for company in companies:
            with transaction.atomic():
                for member in company.admin_members:
                    OrganizationActiveMembersReminderNotification(
                        member,
                        company,
                        active_admins_count=len(company.admin_members),
                        members_url=companies_members_url,
                    ).send()
                    self.stdout.write(f"  - Sent reminder notification to user #{member.pk} for company #{company.pk}")
                company.active_members_email_reminder_last_sent_at = NOW
                company.save(update_fields=["active_members_email_reminder_last_sent_at"])

        # Prescriber organizations
        prescriber_organizations = self.build_query(PrescriberOrganization.objects.all())
        prescriber_organizations_members_url = get_absolute_url(reverse("prescribers_views:members"))
        self.stdout.write(f"Processing {len(prescriber_organizations)} prescriber organizations")
        for prescriber_organization in prescriber_organizations:
            with transaction.atomic():
                for member in prescriber_organization.admin_members:
                    OrganizationActiveMembersReminderNotification(
                        member,
                        prescriber_organization,
                        active_admins_count=len(prescriber_organization.admin_members),
                        members_url=prescriber_organizations_members_url,
                    ).send()
                    self.stdout.write(
                        f"  - Sent reminder notification to user #{member.pk} "
                        f"for prescriber organization #{prescriber_organization.pk}"
                    )
                prescriber_organization.active_members_email_reminder_last_sent_at = NOW
                prescriber_organization.save(update_fields=["active_members_email_reminder_last_sent_at"])

        # Institutions
        institutions = self.build_query(Institution.objects.all())
        institutions_members_url = get_absolute_url(reverse("institutions_views:members"))
        self.stdout.write(f"Processing {len(institutions)} institutions")
        for institution in institutions:
            with transaction.atomic():
                for member in institution.admin_members:
                    OrganizationActiveMembersReminderNotification(
                        member,
                        institution,
                        active_admins_count=len(institution.admin_members),
                        members_url=institutions_members_url,
                    ).send()
                    self.stdout.write(
                        f"  - Sent reminder notification to user #{member.pk} for institution #{institution.pk}"
                    )
                institution.active_members_email_reminder_last_sent_at = NOW
                institution.save(update_fields=["active_members_email_reminder_last_sent_at"])
