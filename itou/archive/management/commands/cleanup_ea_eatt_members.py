from django.db.models import Exists, OuterRef
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.archive.anonymize import (
    annotate_and_prefetch_for_anonymization,
    anonymize_and_delete_professionals,
    anonymize_professionals_without_deletion,
)
from itou.archive.tasks import async_delete_contact
from itou.archive.utils import get_filter_kwargs_on_user_for_related_objects_to_check
from itou.companies.enums import CompanyKind
from itou.companies.models import Company, CompanyMembership
from itou.institutions.models import InstitutionMembership
from itou.prescribers.models import PrescriberMembership
from itou.users.models import User, UserKind
from itou.utils.admin import bulk_add_support_remark_to_objs
from itou.utils.command import BaseCommand


EA_EATT_KINDS = (CompanyKind.EA, CompanyKind.EATT)
BATCH_SIZE = 500


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Perform the EA/EATT cleanup (otherwise dry-run: transaction is rolled back).",
        )

        parser.add_argument(
            "--batch-size",
            action="store",
            type=int,
            default=BATCH_SIZE,
            help="Number of users to process in a batch",
        )

    @dry_runnable
    def handle(self, *args, batch_size, **options):
        self.batch_size = batch_size
        self.logger.info("Start EA/EATT cleanup")

        user_ids = CompanyMembership.include_inactive.filter(
            company__kind__in=EA_EATT_KINDS,
            user__kind__in=UserKind.professionals(),
        ).values_list("user_id", flat=True)
        user_ids_for_update = list(
            User.objects.filter(id__in=user_ids).select_for_update().values_list("id", flat=True)
        )
        self.logger.info("Number of users with EA/EATT memberships: %d", len(user_ids_for_update))

        users_to_anonymize_qs = (
            User.objects.filter(id__in=user_ids_for_update)
            .annotate(
                has_non_ea_eatt_company_membership=Exists(
                    CompanyMembership.include_inactive.filter(user_id=OuterRef("pk")).exclude(
                        company__kind__in=EA_EATT_KINDS
                    )
                ),
                has_prescriber_membership=Exists(PrescriberMembership.include_inactive.filter(user_id=OuterRef("pk"))),
                has_institution_membership=Exists(
                    InstitutionMembership.include_inactive.filter(user_id=OuterRef("pk"))
                ),
            )
            .filter(
                has_non_ea_eatt_company_membership=False,
                has_prescriber_membership=False,
                has_institution_membership=False,
            )
        )
        users_to_anonymize_ids = list(users_to_anonymize_qs.values_list("id", flat=True))
        users_to_detach_ids = [uid for uid in user_ids_for_update if uid not in users_to_anonymize_ids]

        anonymized = self._anonymize_users(users_to_anonymize_ids)
        detached = self._detach_users(users_to_detach_ids)
        self._disable_companies()

        self.logger.info("EA/EATT cleanup done: anonymized=%d detached=%d", anonymized, detached)

        self._check_remaining_memberships()

    def _batched(self, ids):
        for start in range(0, len(ids), self.batch_size):
            yield ids[start : start + self.batch_size]

    def _anonymize_users(self, user_ids):
        if not user_ids:
            return 0

        total_deleted = 0
        total_anonymized = 0
        total_removed_from_contact = 0
        for batch_ids in self._batched(user_ids):
            related_objects_to_check = get_filter_kwargs_on_user_for_related_objects_to_check()
            deletable_ids = set(
                User.objects.filter(id__in=batch_ids).filter(**related_objects_to_check).values_list("id", flat=True)
            )

            users = list(annotate_and_prefetch_for_anonymization(User.objects.filter(id__in=batch_ids)))
            users_to_delete = [user for user in users if user.id in deletable_ids]
            users_to_anonymize = [user for user in users if user.id not in deletable_ids and user.email]
            users_to_remove_from_contact = [user for user in users if user.email]

            anonymize_and_delete_professionals(users_to_delete)
            anonymize_professionals_without_deletion(users_to_anonymize)
            for user in users_to_remove_from_contact:
                async_delete_contact(user.email)

            total_deleted += len(users_to_delete)
            total_anonymized += len(users_to_anonymize)
            total_removed_from_contact += len(users_to_remove_from_contact)

        self.logger.info(
            "EA/EATT anonymization: %d deleted, %d anonymized without deletion, %d removed from contact",
            total_deleted,
            total_anonymized,
            total_removed_from_contact,
        )
        return total_deleted + total_anonymized

    def _detach_users(self, user_ids):
        if not user_ids:
            return 0

        total_deleted = 0
        # will look like: 2026-05-13 12:34:56+02:00
        remark = f"{timezone.localtime().replace(microsecond=0)} - Détachement EA/EATT"
        for batch_ids in self._batched(user_ids):
            deleted, _ = CompanyMembership.include_inactive.filter(
                user_id__in=batch_ids, company__kind__in=EA_EATT_KINDS
            ).delete()
            total_deleted += deleted
            bulk_add_support_remark_to_objs(User.objects.filter(id__in=batch_ids), remark)

        self.logger.info("EA/EATT cleanup: %d memberships removed for %d users", total_deleted, len(user_ids))
        return len(user_ids)

    def _disable_companies(self):
        companies = Company.unfiltered_objects.filter(kind__in=EA_EATT_KINDS)
        now = timezone.now()
        updated = companies.filter(block_job_applications=False).update(
            block_job_applications=True,
            job_applications_blocked_at=now,
        )
        self.logger.info("EA/EATT cleanup: %d companies disabled", updated)

    def _check_remaining_memberships(self):
        """Safety net to check if there are still some EA/EATT memberships left after the cleanup.

        If there are some, it could indicate that some users were missed by the anonymization/detachment
        process: there is no DB constraint ensuring that all EA/EATT memberships correspond to professionals.
        """
        remaining_memberships = CompanyMembership.include_inactive.filter(company__kind__in=EA_EATT_KINDS)
        remaining_ms_count = remaining_memberships.count()
        if remaining_ms_count > 0:
            remaining_users_count = remaining_memberships.values("user_id").distinct().count()
            self.logger.warning(
                "EA/EATT cleanup: %d remaining memberships left for %d distinct users.",
                remaining_ms_count,
                remaining_users_count,
            )
