"""

This script updates existing SIAEs and injects new ones
by joining the following two ASP datasets:
- Vue Structure (has most siae data except kind)
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
from django.db.models import Q

from itou.siaes.management.commands._import_siae.convention import (
    get_creatable_conventions,
    get_deletable_conventions,
    update_existing_conventions,
)
from itou.siaes.management.commands._import_siae.financial_annex import get_creatable_and_deletable_afs
from itou.siaes.management.commands._import_siae.siae import build_siae, could_siae_be_deleted, should_siae_be_created
from itou.siaes.management.commands._import_siae.utils import timeit
from itou.siaes.management.commands._import_siae.vue_af import ACTIVE_SIAE_KEYS
from itou.siaes.management.commands._import_siae.vue_structure import ASP_ID_TO_SIAE_ROW
from itou.siaes.models import Siae, SiaeConvention


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

    def delete_siae(self, siae):
        assert could_siae_be_deleted(siae)
        if not self.dry_run:
            siae.delete()

    @timeit
    def delete_user_created_siaes_without_members(self):
        """
        Siaes created by a user usually have at least one member, their creator.
        However in some cases, itou staff deletes some users, leaving
        potentially user created siaes without member.
        Those siaes cannot be joined by any way and thus are useless.
        Let's clean them up when possible.
        """
        for siae in Siae.objects.filter(source=Siae.SOURCE_USER_CREATED):
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
        for siae in Siae.objects.select_related("convention").filter(source=Siae.SOURCE_ASP, convention__isnull=False):
            assert siae.kind in Siae.ELIGIBILITY_REQUIRED_KINDS

            asp_id = siae.asp_id
            row = ASP_ID_TO_SIAE_ROW.get(asp_id)

            if row is None:
                continue

            new_auth_email = row.auth_email
            auth_email_has_changed = new_auth_email and siae.auth_email != new_auth_email
            if auth_email_has_changed:
                self.update_siae_auth_email(siae, new_auth_email)

            siret_has_changed = row.siret != siae.siret
            if not siret_has_changed:
                continue

            new_siret = row.siret
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

    @timeit
    def delete_inactive_siaes_when_possible(self):
        blocked_deletions = 0
        deletions = 0
        for siae in Siae.objects.filter(source=Siae.SOURCE_ASP).filter(
            Q(convention__isnull=True) | Q(convention__is_active=False)
        ):
            if could_siae_be_deleted(siae):
                self.log(f"siae.id={siae.id} is inactive and without data thus will be deleted")
                self.delete_siae(siae)
                deletions += 1
                continue

            blocked_deletions += 1

        self.log(f"{deletions} siaes will be deleted as inactive and without data")
        self.log(f"{blocked_deletions} siaes are inactive but cannot be deleted")

    @timeit
    def create_new_siaes(self):
        creatable_siae_keys = [(asp_id, kind) for (asp_id, kind) in ACTIVE_SIAE_KEYS if asp_id in ASP_ID_TO_SIAE_ROW]

        creatable_siaes = []

        for (asp_id, kind) in creatable_siae_keys:

            row = ASP_ID_TO_SIAE_ROW.get(asp_id)
            siret = row.siret

            existing_siae_query = Siae.objects.select_related("convention").filter(
                convention__asp_id=asp_id, kind=kind
            )
            if existing_siae_query.exists():
                # Siae with this asp_id already exists, no need to create it.
                existing_siae = existing_siae_query.get()
                if not self.dry_run:
                    # Siret should have been fixed by
                    # update_siret_and_auth_email_of_existing_siaes()
                    # except in a dry-run.
                    assert existing_siae.siret == siret
                assert existing_siae.source == Siae.SOURCE_ASP
                assert existing_siae.kind in Siae.ELIGIBILITY_REQUIRED_KINDS
                continue

            existing_siae_query = Siae.objects.filter(siret=siret, kind=kind)
            if existing_siae_query.exists():
                # Siae with this siret+kind already exists but with wrong source.
                existing_siae = existing_siae_query.get()
                if existing_siae.source == Siae.SOURCE_ASP:
                    assert self.dry_run
                    continue
                assert existing_siae.source in [Siae.SOURCE_USER_CREATED, Siae.SOURCE_STAFF_CREATED]
                assert existing_siae.kind in Siae.ELIGIBILITY_REQUIRED_KINDS
                self.log(
                    f"siae.id={existing_siae.id} already exists "
                    f"with wrong source={existing_siae.source} "
                    f"(source will be fixed to ASP)"
                )
                if not self.dry_run:
                    existing_siae.source = Siae.SOURCE_ASP
                    existing_siae.save()
                continue

            siae = build_siae(row=row, kind=kind)

            if should_siae_be_created(siae):
                assert siae not in creatable_siaes
                creatable_siaes.append(siae)

        self.log("--- beginning of CSV output of all creatable_siaes ---")
        self.log("siret;kind;department;name;address")
        for siae in creatable_siaes:
            self.log(f"{siae.siret};{siae.kind};{siae.department};{siae.name};{siae.address_on_one_line}")
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
    def manage_conventions(self):
        update_existing_conventions(dry_run=self.dry_run)

        creatable_conventions = get_creatable_conventions()
        self.log(f"will create {len(creatable_conventions)} conventions")
        for (convention, siae) in creatable_conventions:
            if not self.dry_run:
                # ONE TIME FIX - Hopefully we can drop it soon.
                # In some very rare edge cases an outdated convention already
                # exists with wrong data, delete it and recreate it.
                # e.g. asp_id=4724 is the only edge case.
                existing_convention_query = SiaeConvention.objects.filter(
                    asp_id=convention.asp_id, kind=convention.kind
                )
                if existing_convention_query.exists():
                    assert convention.asp_id == 4724
                    existing_convention = existing_convention_query.get()
                    self.log(
                        f"delete ghost convention asp_id={convention.asp_id} "
                        f"kind={convention.kind} with all its ghost siaes "
                        f"then recreate it"
                    )
                    for siae in existing_convention.siaes.all():
                        assert siae.id == 5058
                        assert could_siae_be_deleted(siae)
                        siae.delete()
                    existing_convention.delete()
                # END OF ONE TIME FIX - Hopefully we can drop it soon.
                convention.save()
                siae.convention = convention
                siae.save()

        deletable_conventions = get_deletable_conventions()
        self.log(f"will delete {len(deletable_conventions)} conventions")
        for convention in deletable_conventions:
            if not self.dry_run:
                # This will delete the related financial annexes as well.
                convention.delete()

    @timeit
    def manage_financial_annexes(self):
        creatable_afs, deletable_afs = get_creatable_and_deletable_afs(dry_run=self.dry_run)

        self.log(f"will create {len(creatable_afs)} financial annexes")
        for af in creatable_afs:
            if not self.dry_run:
                af.save()

        self.log(f"will delete {len(deletable_afs)} financial annexes")
        for af in deletable_afs:
            if not self.dry_run:
                af.delete()

    @timeit
    def handle(self, dry_run=False, **options):
        self.dry_run = dry_run
        self.set_logger(options.get("verbosity"))

        self.delete_user_created_siaes_without_members()
        self.update_siret_and_auth_email_of_existing_siaes()
        self.create_new_siaes()
        self.manage_conventions()
        self.manage_financial_annexes()
        self.delete_inactive_siaes_when_possible()
        self.check_whether_signup_is_possible_for_all_siaes()
