from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch

from itou.companies.models import Company, CompanyMembership
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    Automatically assign admin role to the 2 most-recently-logged-in active members
    of companies that have no active administrator and no auth_email.

    Companies with an auth_email are excluded because they have a dedicated flow
    allowing members to request the admin role through that address.

    Members who have never logged in are excluded from promotion.
    """

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def handle(self, *args, **options):
        logged_in_members = CompanyMembership.objects.filter(
            company=OuterRef("pk"),
            user__last_login__isnull=False,
        )
        active_admins = CompanyMembership.objects.filter(company=OuterRef("pk"), is_admin=True)

        companies = (
            Company.objects.active()
            .filter(auth_email="")
            .filter(Exists(logged_in_members), ~Exists(active_admins))
            .prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=CompanyMembership.objects.filter(user__last_login__isnull=False)
                    .select_related("user")
                    .order_by("-user__last_login"),
                    to_attr="candidate_memberships",
                )
            )
            .order_by("pk")
        )

        self.logger.info("Processing %d companies", len(companies))

        for company in companies:
            to_promote = company.candidate_memberships[:2]
            with transaction.atomic():
                for membership in to_promote:
                    membership.is_admin = True
                CompanyMembership.objects.bulk_update(to_promote, ["is_admin", "updated_at"])
                for membership in to_promote:
                    company.auto_admin_attribution_email(membership.user).send()
                    self.logger.info(
                        "Promoted user %d to admin of company %d",
                        membership.user_id,
                        company.pk,
                    )
