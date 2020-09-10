"""

This script updates existing SIAEs and injects new ones
by joining the following three ASP datasets:
- Vue Structure (has most siae data except auth_email and kind)
- Liste Correspondants Techniques (has auth_email)
- Vue AF ("Annexes Financières", has kind and all financial annexes)

It should be played again after each upcoming Opening (HDF, the whole country...)
and each time we received a new export from the ASP.

Note that we use dataframes instead of csv reader mainly
because the main CSV has a large number of columns (30+)
and thus we need a proper tool to manage columns by their
name instead of hardcoding column numbers as in `field = row[42]`.

"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.siaes.management.commands._import_siae.liste_correspondants_techniques import EXTERNAL_ID_TO_AUTH_EMAIL
from itou.siaes.management.commands._import_siae.siae import (
    build_siae,
    could_siae_be_deleted,
    does_siae_have_a_valid_convention,
    get_siae_convention_end_date,
    should_siae_be_created,
)
from itou.siaes.management.commands._import_siae.utils import timeit
from itou.siaes.management.commands._import_siae.vue_af import VALID_SIAE_KEYS
from itou.siaes.management.commands._import_siae.vue_structure import EXTERNAL_ID_TO_SIAE_ROW, SIRET_TO_EXTERNAL_ID
from itou.siaes.models import Siae


class Command(BaseCommand):
    """
    Update and sync SIAE data based on latest ASP exports.

    To debug:
        django-admin import_siae --verbosity=2 --dry-run

    When ready:
        django-admin import_siae --verbosity=2
    """

    help = "Update and sync SIAE data based on latest ASP exports."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only print data to import")

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def log(self, message):
        self.logger.debug(message)

    @timeit
    def fix_missing_external_ids(self):
        for siae in Siae.objects.filter(source=Siae.SOURCE_ASP, external_id__isnull=True):
            if siae.siret in SIRET_TO_EXTERNAL_ID:
                external_id = SIRET_TO_EXTERNAL_ID[siae.siret]
                self.log(f"siae.id={siae.id} will be assigned external_id={external_id}")
                if not self.dry_run:
                    siae.external_id = external_id
                    siae.save()

    def delete_siae(self, siae):
        assert could_siae_be_deleted(siae)
        if not self.dry_run:
            siae.delete()

    @timeit
    def delete_siaes_without_external_id(self):
        """
        Any siae which cannot be found in the latest ASP exports
        is a "ghost" siae which should be deleted.
        Of course we check it does not have data.
        """
        for siae in Siae.objects.filter(source=Siae.SOURCE_ASP, external_id__isnull=True):
            if could_siae_be_deleted(siae):
                self.log(f"siae.id={siae.id} without external_id has no data and will be deleted")
                self.delete_siae(siae)
            else:
                self.log(f"siae.id={siae.id} without external_id has data and thus cannot be deleted")

    @timeit
    def delete_user_created_siaes_without_members(self):
        """
        Siaes created by a user usually have at least one member, their creator.
        However in some cases, itou staff deletes some users, leaving
        potentially user created siaes without member.
        Those siaes cannot be joined by any way and thus are useless.
        Let's clean them up.
        """
        for siae in Siae.objects.filter(source=Siae.SOURCE_USER_CREATED).all():
            if not siae.has_members:
                if could_siae_be_deleted(siae):
                    self.log(f"siae.id={siae.id} is user created and has no member thus will be deleted")
                    self.delete_siae(siae)
                else:
                    self.log(
                        f"siae.id={siae.id} is user created and "
                        f"has no member but has job applications thus cannot be deleted"
                    )

    def update_siae_auth_email(self, siae, new_auth_email):
        assert siae.auth_email != new_auth_email
        self.log(
            f"siae.id={siae.id} has changed auth_email from "
            f"{siae.auth_email} to {new_auth_email} (will be updated)"
        )
        if not self.dry_run:
            siae.auth_email = new_auth_email
            siae.save()

    def update_siae_siret(self, siae, new_siret):
        assert siae.siret != new_siret
        self.log(f"siae.id={siae.id} has changed siret from {siae.siret} to {new_siret} (will be updated)")
        if not self.dry_run:
            siae.siret = new_siret
            siae.save()

    @timeit
    def update_siret_and_auth_email_of_existing_siaes(self):
        for siae in Siae.objects.filter(source=Siae.SOURCE_ASP).exclude(external_id__isnull=True):
            assert siae.kind in Siae.ELIGIBILITY_REQUIRED_KINDS
            assert siae.external_id
            row = EXTERNAL_ID_TO_SIAE_ROW.get(siae.external_id)

            if row is None:
                continue

            new_auth_email = EXTERNAL_ID_TO_AUTH_EMAIL.get(siae.external_id)
            auth_email_has_changed = new_auth_email and siae.auth_email != new_auth_email
            if auth_email_has_changed:
                self.update_siae_auth_email(siae, new_auth_email)

            siret_has_changed = row["siret"] != siae.siret
            if not siret_has_changed:
                continue

            new_siret = row["siret"]
            assert siae.siren == new_siret[:9]
            existing_siae = Siae.objects.filter(siret=new_siret, kind=siae.kind).first()

            if not existing_siae:
                self.update_siae_siret(siae, new_siret)
                continue

            # A siae already exists with the new siret.
            # Let's see if one of the two siaes can be safely deleted.
            if could_siae_be_deleted(siae):
                self.log(f"siae.id={siae.id} ghost will be deleted")
                self.delete_siae(siae)
            elif could_siae_be_deleted(existing_siae):
                self.log(f"siae.id={existing_siae.id} ghost will be deleted")
                self.delete_siae(existing_siae)
                self.update_siae_siret(siae, new_siret)
            else:
                self.log(
                    f"siae.id={siae.id} has changed siret from "
                    f"{siae.siret} to {new_siret} but siret "
                    f"already exists (siae.id={existing_siae.id}) "
                    f"and both siaes have data (will *not* be fixed)"
                )

    def update_siae_convention_end_date(self, siae):
        new_convention_end_date = get_siae_convention_end_date(siae)
        if siae.convention_end_date != new_convention_end_date:
            if not self.dry_run:
                siae.convention_end_date = new_convention_end_date
                siae.save()
            return 1
        return 0

    def reactivate_siae(self, siae):
        assert not siae.is_active
        if not self.dry_run:
            siae.is_active = True
            siae.save()

    def deactivate_siae(self, siae):
        assert siae.is_active
        if not self.dry_run:
            siae.is_active = False
            # This starts the grace period.
            siae.deactivated_at = timezone.now()
            siae.save()

    @timeit
    def manage_siae_activation(self):
        reactivations = 0
        deactivations = 0
        deletions = 0
        for siae in Siae.objects.filter(source=Siae.SOURCE_ASP):
            self.update_siae_convention_end_date(siae)
            if does_siae_have_a_valid_convention(siae):
                if not siae.is_active:
                    self.reactivate_siae(siae)
                    reactivations += 1
                continue

            if could_siae_be_deleted(siae):
                self.log(f"siae.id={siae.id} is inactive and without data thus will be deleted")
                self.delete_siae(siae)
                deletions += 1
                continue

            if siae.is_active:
                self.log(
                    f"siae.id={siae.id} kind={siae.kind} name='{siae.display_name}' will be "
                    f"deactivated but has data"
                )
                self.deactivate_siae(siae)
                deactivations += 1

        self.log(f"{deletions} siaes will be deleted as inactive and without data.")
        self.log(f"{deactivations} siaes will be deactivated.")
        self.log(f"{reactivations} siaes will be reactivated.")

    @timeit
    def create_new_siaes(self):
        creatable_siae_keys = [
            (external_id, kind)
            for (external_id, kind) in VALID_SIAE_KEYS
            if external_id in EXTERNAL_ID_TO_SIAE_ROW and external_id in EXTERNAL_ID_TO_AUTH_EMAIL
        ]

        creatable_siaes = []

        for (external_id, kind) in creatable_siae_keys:

            row = EXTERNAL_ID_TO_SIAE_ROW.get(external_id)
            siret = row.siret

            existing_siae_query = Siae.objects.filter(external_id=external_id, kind=kind)
            if existing_siae_query.exists():
                # Siae with this external_id already exists, no need to create it.
                existing_siae = existing_siae_query.get()
                assert existing_siae.siret == siret
                assert existing_siae.source == Siae.SOURCE_ASP
                assert existing_siae.kind in Siae.ELIGIBILITY_REQUIRED_KINDS
                continue

            existing_siae_query = Siae.objects.filter(siret=siret, kind=kind)
            if existing_siae_query.exists():
                # Siae with this siret+kind already exists but with wrong source.
                existing_siae = existing_siae_query.get()
                assert existing_siae.source in [Siae.SOURCE_USER_CREATED, Siae.SOURCE_STAFF_CREATED]
                assert existing_siae.kind in Siae.ELIGIBILITY_REQUIRED_KINDS
                self.log(
                    f"siae.id={existing_siae.id} already exists "
                    f"with wrong source={existing_siae.source} "
                    f"(source will be fixed to ASP)"
                )
                if not self.dry_run:
                    existing_siae.source = Siae.SOURCE_ASP
                    existing_siae.external_id = external_id
                    existing_siae.save()
                continue

            siae = build_siae(row=row, kind=kind)

            if should_siae_be_created(siae):
                assert siae not in creatable_siaes
                creatable_siaes.append(siae)

        self.log("--- beginning of CSV output of all creatable_siaes ---")
        self.log("siret;kind;department;name;external_id;address")
        for siae in creatable_siaes:
            self.log(
                f"{siae.siret};{siae.kind};{siae.department};{siae.name};{siae.external_id};{siae.address_on_one_line}"
            )
            if not self.dry_run:
                siae.save()
        self.log("--- end of CSV output of all creatable_siaes ---")

        self.log(f"{len(creatable_siaes)} structures will be created")
        self.log(f"{len([s for s in creatable_siaes if s.coords])} structures will have geolocation")

    @timeit
    def check_whether_signup_is_possible_for_all_siaes(self):
        for siae in Siae.objects.all():
            if not siae.has_members and not siae.auth_email:
                msg = (
                    f"Signup is impossible for siae id={siae.id} siret={siae.siret} "
                    f"kind={siae.kind} dpt={siae.department} source={siae.source} "
                    f"created_by={siae.created_by} siae_email={siae.email}"
                )
                self.log(msg)

    @timeit
    def handle(self, dry_run=False, **options):
        self.dry_run = dry_run
        self.set_logger(options.get("verbosity"))

        # Ugly one-time shot code to fix legacy issue - drop me afterwards!
        # Most likely in the past the import_siae did incorrectly set an
        # external_id on siaes of non-ASP source.
        for siae in Siae.objects.exclude(external_id__isnull=True).exclude(source=Siae.SOURCE_ASP).all():
            self.log(
                f"[legacy bugfix] non-ASP siae.id={siae.id} has "
                f"external_id={siae.external_id} but should not, external_id will be removed"
            )
            # Just to be safe.
            assert siae.external_id
            assert siae.source != Siae.SOURCE_ASP
            # Fix even in dry-run otherwise breaks later in the dry-run.
            siae.external_id = None
            siae.save()
        # End of one-time shot code. Drop me ASAP after production!

        self.fix_missing_external_ids()
        self.delete_siaes_without_external_id()
        self.delete_user_created_siaes_without_members()
        self.update_siret_and_auth_email_of_existing_siaes()
        self.manage_siae_activation()
        self.create_new_siaes()
        self.check_whether_signup_is_possible_for_all_siaes()
