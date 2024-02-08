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

from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.companies.management.commands._import_siae.convention import (
    check_convention_data_consistency,
    get_creatable_conventions,
    update_existing_conventions,
)
from itou.companies.management.commands._import_siae.financial_annex import get_creatable_and_deletable_afs
from itou.companies.management.commands._import_siae.siae import (
    build_siae,
)
from itou.companies.management.commands._import_siae.utils import could_siae_be_deleted
from itou.companies.management.commands._import_siae.vue_af import (
    get_active_siae_keys,
    get_af_number_to_row,
    get_vue_af_df,
)
from itou.companies.management.commands._import_siae.vue_structure import (
    get_siret_to_siae_row,
    get_vue_structure_df,
)
from itou.companies.models import Company, SiaeConvention
from itou.utils.command import BaseCommand
from itou.utils.emails import send_email_messages
from itou.utils.python import timeit


class Command(BaseCommand):
    """
    Update and sync SIAE data based on latest ASP exports.

    Run the following command:
        django-admin import_siae
    """

    help = "Update and sync SIAE data based on latest ASP exports."
    fatal_errors = 0

    @timeit
    def delete_user_created_siaes_without_members(self):
        """
        Siaes created by a user usually have at least one member, their creator.
        However in some cases, itou staff deletes some users, leaving
        potentially user created siaes without member.
        Those siaes cannot be joined by any way and thus are useless.
        Let's clean them up when possible.
        """
        for siae in Company.objects.prefetch_related("memberships").filter(
            members__isnull=True, source=Company.SOURCE_USER_CREATED
        ):
            if not siae.has_members:
                if could_siae_be_deleted(siae):
                    self.stdout.write(f"siae.id={siae.id} is user created and has no member thus will be deleted")
                    siae.delete()
                else:
                    self.stdout.write(
                        f"FATAL ERROR: siae.id={siae.id} is user created and "
                        f"has no member but has job applications thus cannot be deleted"
                    )
                    self.fatal_errors += 1

    @timeit
    def manage_staff_created_siaes(self):
        """
        Itou staff regularly creates siaes manually when ASP data lags behind for some specific employers.

        Normally the SIRET later appears in ASP data then the siae is converted to ASP source by `create_new_siaes`.

        But sometimes a staff created siae's SIRET never appear in ASP data. We wait 90 days (as decided with staff
        team) before considering it invalid and attempting deleting it.

        If the siae cannot be deleted because it has data, a warning will be shown to supportix.
        """
        # Sometimes our staff creates a siae then later attaches it manually to the correct convention. In that
        # case it should be converted to a regular user created siae so that the usual convention logic applies.
        for siae in Company.objects.filter(
            kind__in=SIAE_WITH_CONVENTION_KINDS, source=Company.SOURCE_STAFF_CREATED, convention__isnull=False
        ):
            self.stdout.write(f"converted staff created siae.id={siae.id} to user created siae as it has a convention")
            siae.source = Company.SOURCE_USER_CREATED
            siae.save()

        three_months_ago = timezone.now() - timezone.timedelta(days=90)
        staff_created_siaes = Company.objects.filter(
            kind__in=SIAE_WITH_CONVENTION_KINDS,
            source=Company.SOURCE_STAFF_CREATED,
        )

        recent_unconfirmed_siaes = staff_created_siaes.filter(created_at__gte=three_months_ago)
        self.stdout.write(
            f"{recent_unconfirmed_siaes.count()} siaes created recently by staff"
            f" (still waiting for ASP data to be confirmed)"
        )

        old_unconfirmed_siaes = staff_created_siaes.filter(created_at__lt=three_months_ago)
        self.stdout.write(
            f"{old_unconfirmed_siaes.count()} siaes created by staff should be deleted as they are unconfirmed"
        )
        for siae in old_unconfirmed_siaes:
            if could_siae_be_deleted(siae):
                self.stdout.write(f"deleted unconfirmed siae.id={siae.id} created by staff a while ago")
                siae.delete()
            else:
                self.stdout.write(
                    f"FATAL ERROR: Please fix unconfirmed staff created siae.id={siae.id}"
                    f" by either deleting it or attaching it to the correct convention"
                )
                self.fatal_errors += 1

    def update_siae_auth_email(self, siae, new_auth_email):
        assert siae.auth_email != new_auth_email
        siae.auth_email = new_auth_email
        siae.save()

    def update_siae_siret(self, siae, new_siret):
        assert siae.siret != new_siret
        self.stdout.write(f"siae.id={siae.id} has changed siret from {siae.siret} to {new_siret} (will be updated)")
        siae.siret = new_siret
        siae.save()

    @timeit
    def update_siret_and_auth_email_of_existing_siaes(self, siret_to_siae_row):
        auth_email_updates = 0

        asp_id_to_siae_row = {row.asp_id: row for row in siret_to_siae_row.values()}
        for siae in Company.objects.select_related("convention").filter(
            source=Company.SOURCE_ASP, convention__isnull=False
        ):
            assert siae.should_have_convention

            row = asp_id_to_siae_row[siae.convention.asp_id]

            if row is None:
                continue

            new_auth_email = row.auth_email
            auth_email_has_changed = new_auth_email and siae.auth_email != new_auth_email
            if auth_email_has_changed:
                self.update_siae_auth_email(siae, new_auth_email)
                auth_email_updates += 1

            siret_has_changed = row.siret != siae.siret
            if not siret_has_changed:
                continue

            new_siret = row.siret
            assert siae.siren == new_siret[:9]
            existing_siae = Company.objects.filter(siret=new_siret, kind=siae.kind).first()

            if not existing_siae:
                self.update_siae_siret(siae, new_siret)
                continue

            def fmt(siae):
                if siae.convention is None:
                    return f"{siae.source} {siae.siret} convention=None"
                return f"{siae.source} {siae.siret} convention.id={siae.convention.id} asp_id={siae.convention.asp_id}"

            self.stdout.write(
                f"FATAL ERROR: siae.id={siae.id} ({fmt(siae)}) has changed siret from "
                f"{siae.siret} to {new_siret} but new siret is already used by "
                f"siae.id={existing_siae.id} ({fmt(existing_siae)}) "
            )
            self.fatal_errors += 1

        self.stdout.write(f"{auth_email_updates} siae.auth_email fields will be updated")

    @timeit
    def cleanup_siaes_after_grace_period(self):
        blocked_deletions = 0
        deletions = 0

        for siae in Company.objects.select_related("convention"):
            if not siae.grace_period_has_expired:
                continue
            if could_siae_be_deleted(siae):
                siae.delete()
                deletions += 1
                continue
            blocked_deletions += 1

        self.stdout.write(f"{deletions} siaes past their grace period will be deleted")
        self.stdout.write(f"{blocked_deletions} siaes past their grace period cannot be deleted")

    @timeit
    def create_new_siaes(self, siret_to_siae_row, active_siae_keys):
        asp_id_to_siae_row = {row.asp_id: row for row in siret_to_siae_row.values()}
        creatable_siae_keys = [(asp_id, kind) for (asp_id, kind) in active_siae_keys if asp_id in asp_id_to_siae_row]

        creatable_siaes = []

        for asp_id, kind in creatable_siae_keys:
            row = asp_id_to_siae_row.get(asp_id)
            siret = row.siret

            existing_siae_query = Company.objects.select_related("convention").filter(
                convention__asp_id=asp_id, kind=kind
            )
            if existing_siae_query.exists():
                # Siaes with this asp_id already exist, no need to create one more.
                total_existing_siaes_with_asp_source = 0
                for existing_siae in existing_siae_query.all():
                    assert existing_siae.should_have_convention
                    if existing_siae.source == Company.SOURCE_ASP:
                        total_existing_siaes_with_asp_source += 1
                        # Siret should have been fixed by update_siret_and_auth_email_of_existing_siaes().
                        assert existing_siae.siret == siret
                    else:
                        assert existing_siae.source == Company.SOURCE_USER_CREATED

                # Duplicate siaes should have been deleted.
                assert total_existing_siaes_with_asp_source == 1
                continue

            existing_siae_query = Company.objects.filter(siret=siret, kind=kind)
            if existing_siae_query.exists():
                existing_siae = existing_siae_query.get()
                if existing_siae.source == Company.SOURCE_ASP:
                    # Sometimes the siae already exists but was not detected in the first queryset above because it
                    # has the wrong asp_id. Such an edge case is fixed in another method `update_existing_conventions`.
                    continue
                # Siae with this siret+kind already exists but with wrong source.
                assert existing_siae.source in [Company.SOURCE_USER_CREATED, Company.SOURCE_STAFF_CREATED]
                assert existing_siae.should_have_convention
                self.stdout.write(
                    f"siae.id={existing_siae.id} already exists "
                    f"with wrong source={existing_siae.source} "
                    f"(source will be fixed to ASP)"
                )
                existing_siae.source = Company.SOURCE_ASP
                existing_siae.convention = None
                existing_siae.save()
                continue

            assert not SiaeConvention.objects.filter(asp_id=asp_id, kind=kind).exists()

            if (row.asp_id, kind) in active_siae_keys:
                creatable_siaes.append(build_siae(row, kind, is_active=True))

        self.stdout.write("--- beginning of CSV output of all creatable_siaes ---")
        self.stdout.write("siret;kind;department;name;address")
        for siae in creatable_siaes:
            self.stdout.write(f"{siae.siret};{siae.kind};{siae.department};{siae.name};{siae.address_on_one_line}")
            siae.save()
        self.stdout.write("--- end of CSV output of all creatable_siaes ---")

        send_email_messages(siae.activate_your_account_email() for siae in creatable_siaes)

        self.stdout.write(f"{len(creatable_siaes)} structures will be created")
        self.stdout.write(f"{len([s for s in creatable_siaes if s.coords])} structures will have geolocation")

    @timeit
    def check_whether_signup_is_possible_for_all_siaes(self):
        for siae in (
            Company.objects.filter(
                auth_email="",
            )
            .exclude(  # Exclude siae which have at least one active member.
                companymembership__is_active=True,
            )
            .distinct()
        ):
            self.stdout.write(
                f"FATAL ERROR: signup is impossible for siae.id={siae.id} siret={siae.siret} "
                f"kind={siae.kind} dpt={siae.department} source={siae.source} "
                f"created_by={siae.created_by} siae.email={siae.email}"
            )
            self.fatal_errors += 1

    @timeit
    def create_conventions(self, vue_af_df, siret_to_siae_row, active_siae_keys):
        creatable_conventions = get_creatable_conventions(vue_af_df, siret_to_siae_row, active_siae_keys)
        self.stdout.write(f"will create {len(creatable_conventions)} conventions")
        for convention, siae in creatable_conventions:
            assert not SiaeConvention.objects.filter(asp_id=convention.asp_id, kind=convention.kind).exists()
            convention.save()
            assert convention.siaes.count() == 0
            siae.convention = convention
            siae.save()
            assert convention.siaes.filter(source=Company.SOURCE_ASP).count() == 1

    @timeit
    @transaction.atomic()
    def delete_conventions(self):
        deletable_conventions = SiaeConvention.objects.filter(siaes__isnull=True)
        self.stdout.write(f"will delete {len(deletable_conventions)} conventions")
        for convention in deletable_conventions:
            # This will delete the related financial annexes as well.
            convention.delete()

    @timeit
    def manage_financial_annexes(self, af_number_to_row):
        creatable_afs, deletable_afs = get_creatable_and_deletable_afs(af_number_to_row)

        self.stdout.write(f"will create {len(creatable_afs)} financial annexes")
        for af in creatable_afs:
            af.save()

        self.stdout.write(f"will delete {len(deletable_afs)} financial annexes")
        for af in deletable_afs:
            af.delete()

    @timeit
    def handle(self, **options):
        siret_to_siae_row = get_siret_to_siae_row(get_vue_structure_df())

        vue_af_df = get_vue_af_df()
        af_number_to_row = get_af_number_to_row(vue_af_df)
        active_siae_keys = get_active_siae_keys(vue_af_df)

        self.delete_user_created_siaes_without_members()
        self.manage_staff_created_siaes()
        self.update_siret_and_auth_email_of_existing_siaes(siret_to_siae_row)
        update_existing_conventions(siret_to_siae_row, active_siae_keys)
        self.create_new_siaes(siret_to_siae_row, active_siae_keys)
        self.create_conventions(vue_af_df, siret_to_siae_row, active_siae_keys)
        self.delete_conventions()
        self.manage_financial_annexes(af_number_to_row)
        self.cleanup_siaes_after_grace_period()

        # Run some updates a second time.
        update_existing_conventions(siret_to_siae_row, active_siae_keys)
        self.update_siret_and_auth_email_of_existing_siaes(siret_to_siae_row)
        self.delete_conventions()

        # Final checks.
        check_convention_data_consistency()
        self.check_whether_signup_is_possible_for_all_siaes()

        if self.fatal_errors >= 1:
            raise CommandError(
                "*** FATAL ERROR(S) ***"
                "The command completed all its actions successfully but at least one fatal error needs "
                "manual resolution, see command output"
            )

        self.stdout.write("All done!")
