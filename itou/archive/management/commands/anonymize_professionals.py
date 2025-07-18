from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.archive.models import AnonymizedProfessional
from itou.archive.tasks import async_delete_contact
from itou.archive.utils import get_filter_kwargs_on_user_for_related_objects_to_check, get_year_month_or_none
from itou.companies.models import CompanyMembership
from itou.institutions.models import InstitutionMembership
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.prescribers.models import PrescriberMembership
from itou.users.models import User, UserKind
from itou.users.notifications import ArchiveUser
from itou.utils.command import BaseCommand, dry_runnable
from itou.utils.constants import GRACE_PERIOD


BATCH_SIZE = 100


class Command(BaseCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the anonymization of professionals",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of professionals to process in a batch",
        )

    def reset_notified_professionals_with_recent_activity(self):
        self.logger.info("Reseting inactive professionals with recent activity")

        users_to_reset_qs = User.objects.filter(
            kind__in=UserKind.professionals(),
            upcoming_deletion_notified_at__isnull=False,
            last_login__gte=F("upcoming_deletion_notified_at"),
        )

        reset_nb = users_to_reset_qs.update(upcoming_deletion_notified_at=None)
        self.logger.info("Reset notified professionals with recent activity: %s", reset_nb)

    @transaction.atomic
    def anonymize_professionals_after_grace_period(self):
        now = timezone.now()
        grace_period_since = now - GRACE_PERIOD
        self.logger.info("Archiving professionals after grace period, notified before: %s", grace_period_since)

        users = self.get_users(grace_period_since)

        # split users to anonymize into those that can be deleted and those that can only be anonymized
        users_to_delete = self.get_users_to_anonymize_and_delete(users)

        # users that can be anonymized but not deleted. Users without email are already anonymized
        users_to_anonymize = [user for user in users if user not in users_to_delete and user.email is not None]

        # users to anonymize or delete that have an email set
        users_to_remove_from_contact = [user for user in users if user.email]

        for user in users:
            ArchiveUser(user).send()

        self.anonymize_and_delete_professionals(users_to_delete)
        self.anonymize_professionals_without_deletion(users_to_anonymize)
        self.remove_from_contact(users_to_remove_from_contact)

        self.logger.info("Anonymized professionals after grace period, count: %d", len(users))
        self.logger.info(
            "Included in this count: %d to delete, %d to remove from contact",
            len(users_to_delete),
            len(users_to_remove_from_contact),
        )

    def get_users(self, grace_period_since):
        return list(
            User.objects.filter(
                kind__in=UserKind.professionals(), upcoming_deletion_notified_at__lte=grace_period_since
            )
            .annotate(is_deactivated=Q(email__isnull=True))
            .order_by("is_deactivated", "upcoming_deletion_notified_at")
            .select_for_update(of=("self",), skip_locked=True)[: self.batch_size]
        )

    def get_users_to_anonymize_and_delete(self, users):
        related_objects_to_check = get_filter_kwargs_on_user_for_related_objects_to_check()
        has_membership_in_authorized_organization_sqs = PrescriberMembership.objects.filter(
            user_id=OuterRef("id"), organization__authorization_status=PrescriberAuthorizationStatus.VALIDATED
        )
        return list(
            User.objects.filter(id__in=[user.id for user in users])
            .filter(**related_objects_to_check)
            .annotate(has_membership_in_authorized_organization=Exists(has_membership_in_authorized_organization_sqs))
            .prefetch_related(
                "companymembership_set",
                "institutionmembership_set",
                "prescribermembership_set",
            )
        )

    def make_anonymized_professional(self, user):
        memberships = [
            *user.companymembership_set.all(),
            *user.institutionmembership_set.all(),
            *user.prescribermembership_set.all(),
        ]
        return AnonymizedProfessional(
            date_joined=get_year_month_or_none(user.date_joined),
            first_login=get_year_month_or_none(user.first_login),
            last_login=get_year_month_or_none(user.last_login),
            department=user.department,
            title=user.title,
            kind=user.kind,
            number_of_memberships=len(memberships),
            number_of_active_memberships=sum(m.is_active for m in memberships),
            number_of_memberships_as_administrator=sum(m.is_admin for m in memberships),
            had_memberships_in_authorized_organization=user.has_membership_in_authorized_organization,
            identity_provider=user.identity_provider,
        )

    def anonymize_and_delete_professionals(self, users):
        AnonymizedProfessional.objects.bulk_create([self.make_anonymized_professional(user) for user in users])
        User.objects.filter(id__in=[user.id for user in users]).delete()

    def anonymize_professionals_without_deletion(self, users):
        user_ids = [user.id for user in users]
        for model in [CompanyMembership, InstitutionMembership, PrescriberMembership]:
            model.objects.filter(user_id__in=user_ids).update(is_active=False)

        User.objects.filter(id__in=user_ids).update(
            is_active=False,
            password=make_password(None),
            email=None,
            phone="",
            address_line_1="",
            address_line_2="",
            post_code="",
            city="",
            coords=None,
            insee_city=None,
        )

    def remove_from_contact(self, users):
        for user in users:
            async_delete_contact(user.email)

    @monitor(
        monitor_slug="anonymize_professionals",
        monitor_config={
            "schedule": {"type": "crontab", "value": "0 7-20 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    @dry_runnable
    def handle(self, *args, batch_size, **options):
        if settings.SUSPEND_ANONYMIZE_PROFESSIONALS:
            self.logger.info("Anonymizing professionals is suspended, exiting command")
            return
        self.batch_size = batch_size
        self.logger.info("Start anonymizing professionals")

        self.reset_notified_professionals_with_recent_activity()
        self.anonymize_professionals_after_grace_period()
