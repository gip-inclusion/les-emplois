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
from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.siaes.enums import SIAE_WITH_CONVENTION_KINDS
from itou.siaes.management.commands._import_siae.convention import (
    check_convention_data_consistency,
    get_creatable_conventions,
    get_deletable_conventions,
    update_existing_conventions,
)
from itou.siaes.management.commands._import_siae.financial_annex import get_creatable_and_deletable_afs
from itou.siaes.management.commands._import_siae.siae import build_siae, should_siae_be_created
from itou.siaes.management.commands._import_siae.utils import could_siae_be_deleted
from itou.siaes.management.commands._import_siae.vue_af import ACTIVE_SIAE_KEYS
from itou.siaes.management.commands._import_siae.vue_structure import ASP_ID_TO_SIAE_ROW
from itou.siaes.models import Siae, SiaeConvention
from itou.utils.emails import send_email_messages
from itou.utils.python import timeit


class Command(BaseCommand):
    """
    Update and sync SIAE data based on latest ASP exports.

    Run the following command:
        django-admin import_siae
    """

    help = "Update and sync SIAE data based on latest ASP exports."

    def delete_siae(self, siae):
        assert could_siae_be_deleted(siae)
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
        for siae in Siae.objects.prefetch_related("memberships").filter(
            members__isnull=True, source=Siae.SOURCE_USER_CREATED
        ):
            if not siae.has_members:
                if could_siae_be_deleted(siae):
                    self.stdout.write(f"siae.id={siae.id} is user created and has no member thus will be deleted")
                    self.delete_siae(siae)
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
        for siae in Siae.objects.filter(
            kind__in=SIAE_WITH_CONVENTION_KINDS, source=Siae.SOURCE_STAFF_CREATED, convention__isnull=False
        ):
            self.stdout.write(f"converted staff created siae.id={siae.id} to user created siae as it has a convention")
            siae.source = Siae.SOURCE_USER_CREATED
            siae.save()

        three_months_ago = timezone.now() - timezone.timedelta(days=90)
        staff_created_siaes = Siae.objects.filter(
            kind__in=SIAE_WITH_CONVENTION_KINDS,
            source=Siae.SOURCE_STAFF_CREATED,
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
                self.delete_siae(siae)
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
    def update_siret_and_auth_email_of_existing_siaes(self):
        auth_email_updates = 0
        for siae in Siae.objects.select_related("convention").filter(source=Siae.SOURCE_ASP, convention__isnull=False):
            assert siae.should_have_convention

            asp_id = siae.asp_id
            row = ASP_ID_TO_SIAE_ROW.get(asp_id)

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
            existing_siae = Siae.objects.filter(siret=new_siret, kind=siae.kind).first()

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

        for siae in Siae.objects.select_related("convention").all():
            if not siae.grace_period_has_expired:
                continue
            if could_siae_be_deleted(siae):
                self.delete_siae(siae)
                deletions += 1
                continue
            blocked_deletions += 1

        self.stdout.write(f"{deletions} siaes past their grace period will be deleted")
        self.stdout.write(f"{blocked_deletions} siaes past their grace period cannot be deleted")

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
                # Siaes with this asp_id already exist, no need to create one more.
                total_existing_siaes_with_asp_source = 0
                for existing_siae in existing_siae_query.all():
                    assert existing_siae.should_have_convention
                    if existing_siae.source == Siae.SOURCE_ASP:
                        total_existing_siaes_with_asp_source += 1
                        # Siret should have been fixed by update_siret_and_auth_email_of_existing_siaes().
                        assert existing_siae.siret == siret
                    else:
                        assert existing_siae.source == Siae.SOURCE_USER_CREATED

                # Duplicate siaes should have been deleted.
                assert total_existing_siaes_with_asp_source == 1
                continue

            existing_siae_query = Siae.objects.filter(siret=siret, kind=kind)
            if existing_siae_query.exists():
                existing_siae = existing_siae_query.get()
                if existing_siae.source == Siae.SOURCE_ASP:
                    # Sometimes the siae already exists but was not detected in the first queryset above because it
                    # has the wrong asp_id. Such an edge case is fixed in another method `update_existing_conventions`.
                    continue
                # Siae with this siret+kind already exists but with wrong source.
                assert existing_siae.source in [Siae.SOURCE_USER_CREATED, Siae.SOURCE_STAFF_CREATED]
                assert existing_siae.should_have_convention
                self.stdout.write(
                    f"siae.id={existing_siae.id} already exists "
                    f"with wrong source={existing_siae.source} "
                    f"(source will be fixed to ASP)"
                )
                existing_siae.source = Siae.SOURCE_ASP
                existing_siae.convention = None
                existing_siae.save()
                continue

            assert not SiaeConvention.objects.filter(asp_id=asp_id, kind=kind).exists()

            siae = build_siae(row=row, kind=kind)

            if should_siae_be_created(siae):
                assert siae not in creatable_siaes
                creatable_siaes.append(siae)

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
            Siae.objects.filter(
                auth_email="",
            )
            .exclude(  # Exclude siae which have at least one active member.
                siaemembership__is_active=True,
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
    def create_conventions(self):
        creatable_conventions = get_creatable_conventions()
        self.stdout.write(f"will create {len(creatable_conventions)} conventions")
        for (convention, siae) in creatable_conventions:
            assert not SiaeConvention.objects.filter(asp_id=convention.asp_id, kind=convention.kind).exists()
            convention.save()
            assert convention.siaes.count() == 0
            siae.convention = convention
            siae.save()
            assert convention.siaes.filter(source=Siae.SOURCE_ASP).count() == 1

    @timeit
    def delete_conventions(self):
        deletable_conventions = get_deletable_conventions()
        self.stdout.write(f"will delete {len(deletable_conventions)} conventions")
        for convention in deletable_conventions:
            assert convention.siaes.count() == 0
            # This will delete the related financial annexes as well.
            convention.delete()

    @timeit
    def manage_financial_annexes(self):
        creatable_afs, deletable_afs = get_creatable_and_deletable_afs()

        self.stdout.write(f"will create {len(creatable_afs)} financial annexes")
        for af in creatable_afs:
            af.save()

        self.stdout.write(f"will delete {len(deletable_afs)} financial annexes")
        for af in deletable_afs:
            af.delete()

    @timeit
    def handle(self, **options):
        self.fatal_errors = 0

        self.delete_user_created_siaes_without_members()
        self.manage_staff_created_siaes()
        self.update_siret_and_auth_email_of_existing_siaes()
        update_existing_conventions()
        self.create_new_siaes()
        self.create_conventions()
        self.delete_conventions()
        self.manage_financial_annexes()
        self.cleanup_siaes_after_grace_period()

        # Run some updates a second time.
        update_existing_conventions()
        self.update_siret_and_auth_email_of_existing_siaes()
        self.delete_conventions()

        # Final checks.
        check_convention_data_consistency()
        self.check_whether_signup_is_possible_for_all_siaes()

        if self.fatal_errors >= 1:
            raise RuntimeError(
                "The command completed all its actions successfully but at least one fatal error needs "
                "manual resolution, see command output"
            )
