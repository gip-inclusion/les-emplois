import json

from django.utils.dateparse import parse_date, parse_datetime
from itoutils.django.commands import dry_runnable

from itou.companies.models import Company
from itou.insertion.models import Orientation, Service
from itou.job_applications.enums import SenderKind
from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    help = (
        "One-shot backfill of orientations previously held by Dora. "
        "Reads the JSON export produced by Dora's `export_emplois_orientations` "
        "command and creates the matching local Orientation objects."
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the JSON export produced by Dora",
        )
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Persist the imported orientations (otherwise the transaction is rolled back)",
        )

    def _build_lookups(self, entries):
        """Prefetch every referenced object in bulk to avoid per-row queries.

        Dora stores our own public identifiers verbatim in each entry
        (see itou/www/insertion_views/views.py): beneficiary/prescriber
        `public_id` and organization `uid`. The targeted service is exposed
        through its `uid` (`<source>--<id>`).
        """
        user_public_ids = set()
        org_uids = set()
        service_uids = set()
        for entry in entries:
            user_public_ids.add(entry["beneficiary_id"])
            if entry["prescriber_id"]:
                user_public_ids.add(entry["prescriber_id"])
            org_uids.add(entry["structure_id"])
            service_uids.add(entry["service_id"])

        # Keys are stringified: identifiers come from JSON as strings, whereas
        # `public_id` / `uid` are UUID fields (`Service.uid` is already a string).
        users = {str(u.public_id): u for u in User.objects.filter(public_id__in=user_public_ids)}
        prescriber_organizations = {str(o.uid): o for o in PrescriberOrganization.objects.filter(uid__in=org_uids)}
        companies = {str(c.uid): c for c in Company.objects.filter(uid__in=org_uids)}
        services = {str(s.uid): s for s in Service.objects.filter(uid__in=service_uids)}
        return users, prescriber_organizations, companies, services

    def _build_orientation(self, entry, users, prescriber_organizations, companies, services):
        """Return an unsaved Orientation, or None if a referenced object is missing."""
        sync_uid = entry["emplois_sync_uid"]

        beneficiary = users.get(entry["beneficiary_id"])
        if beneficiary is None:
            self.logger.warning("Skipping orientation %s: unknown beneficiary", sync_uid)
            return None

        prescriber_id = entry["prescriber_id"]
        sender = users.get(prescriber_id) if prescriber_id else None
        if sender is None:
            self.logger.warning("Skipping orientation %s: unknown sender", sync_uid)
            return None

        service = services.get(entry["service_id"])
        if service is None:
            self.logger.warning("Skipping orientation %s: unknown service %s", sync_uid, entry["service_id"])
            return None

        # The sender kind is not stored by Dora: we recover it from the referenced
        # organization, a prescriber organization or a company (both share `uid`).
        structure_id = entry["structure_id"]
        if prescriber_organization := prescriber_organizations.get(structure_id):
            sender_kind = SenderKind.PRESCRIBER
            sender_prescriber_organization = prescriber_organization
            sender_company = None
        elif company := companies.get(structure_id):
            sender_kind = SenderKind.EMPLOYER
            sender_prescriber_organization = None
            sender_company = company
        else:
            self.logger.warning("Skipping orientation %s: unknown organization %s", sync_uid, structure_id)
            return None

        return Orientation(
            id=sync_uid,
            beneficiary=beneficiary,
            sender=sender,
            sender_kind=sender_kind,
            sender_prescriber_organization=sender_prescriber_organization,
            sender_company=sender_company,
            service=service,
            beneficiary_contact_preferences=entry["beneficiary_contact_preferences"],
            beneficiary_other_contact_method=entry["beneficiary_other_contact_method"],
            beneficiary_availability=parse_date(entry["beneficiary_availability"])
            if entry["beneficiary_availability"]
            else None,
            requirements=entry["requirements"],
            situation=entry["situation"],
            situation_other=entry["situation_other"],
            referent_last_name=entry["referent_last_name"],
            referent_first_name=entry["referent_first_name"],
            referent_phone=entry["referent_phone"],
            referent_email=entry["referent_email"],
            orientation_reasons=entry["orientation_reasons"],
            status=entry["status"],
            processing_date=parse_datetime(entry["processing_date"]) if entry["processing_date"] else None,
            duration_weekly_hours=entry["duration_weekly_hours"],
            duration_weeks=entry["duration_weeks"],
            data_protection_commitment=entry["data_protection_commitment"],
            attachments=entry["beneficiary_attachments"],
            created_at=parse_datetime(entry["creation_date"]),
        )

    @dry_runnable
    def handle(self, *args, file, wet_run, **options):
        self.wet_run = wet_run

        with open(file, encoding="utf-8") as f:
            entries = json.load(f)

        self.logger.info("Read %d orientation(s) from %s", len(entries), file)

        lookups = self._build_lookups(entries)

        # Orientations already present locally are left untouched: this is a backfill.
        all_ids = [entry["emplois_sync_uid"] for entry in entries]
        existing_ids = {str(pk) for pk in Orientation.objects.filter(id__in=all_ids).values_list("id", flat=True)}

        to_create = []
        skipped_existing = 0
        skipped_missing = 0
        for entry in entries:
            if str(entry["emplois_sync_uid"]) in existing_ids:
                skipped_existing += 1
                continue
            orientation = self._build_orientation(entry, *lookups)
            if orientation is None:
                skipped_missing += 1
                continue
            to_create.append(orientation)

        Orientation.objects.bulk_create(to_create)

        self.logger.info(
            "%s orientations: created=%d, skipped_existing=%d, skipped_missing_references=%d",
            "Imported" if wet_run else "Would import (dry-run)",
            len(to_create),
            skipped_existing,
            skipped_missing,
        )
