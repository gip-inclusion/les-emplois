"""

SiaeConvention object logic used by the import_siae.py script is gathered here.

"""

import datetime

from django.db import transaction
from django.utils import timezone

from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.companies.models import Company, SiaeConvention


CONVENTION_DEACTIVATION_THRESHOLD = 200


def update_existing_conventions(siret_to_siae_row, conventions_by_siae_key):
    """
    Update existing conventions, mainly the is_active field,
    and check data integrity on the fly.
    """
    conventions_to_deactivate = []
    reactivations = 0
    three_months_ago = timezone.now() - timezone.timedelta(days=90)

    managed_siaes_with_conventions = Company.objects.filter(
        source=Company.SOURCE_ASP, convention__isnull=False
    ).select_related("convention")
    for siae in managed_siaes_with_conventions:
        convention = siae.convention
        assert convention.kind == siae.kind
        assert convention.siren_signature == siae.siren

        if siae.siret not in siret_to_siae_row:
            # At some point, old C1 siaes stop existing in the latest FluxIAE file.
            # If they still have C1 data they could not be deleted in an earlier step and thus will stay in
            # the C1 database forever, we should leave them untouched.
            if convention.is_active:
                conventions_to_deactivate.append(convention)
            continue

        row = siret_to_siae_row[siae.siret]
        updated_fields = set()

        # Sometimes the same siret is attached to one asp_id in one export and to another asp_id in the next export.
        # In other words, the siae convention asp_id has changed and should be updated.
        # Ideally this should never happen because the asp_id is supposed to be an immutable id of the structure
        # in ASP data, but one can only hope.
        if convention.asp_id != row.asp_id:
            print(
                f"convention.id={convention.id} has changed asp_id from "
                f"{convention.asp_id} to {row.asp_id} (will be updated)"
            )
            assert not SiaeConvention.objects.filter(asp_id=row.asp_id, kind=siae.kind).exists()
            convention.asp_id = row.asp_id
            convention.save(update_fields={"asp_id"})
            continue

        # Siret_signature can change from one export to the next!
        # e.g. asp_id=4948 has changed from 81051848000027 to 81051848000019
        if convention.siret_signature != row.siret_signature:
            print(
                f"convention.id={convention.id} has changed siret_signature from "
                f"{convention.siret_signature} to {row.siret_signature} (will be updated)"
            )
            convention.siret_signature = row.siret_signature
            updated_fields.add("siret_signature")

        try:
            should_be_active = conventions_by_siae_key[(row.asp_id, siae.kind)].is_active
        except KeyError:
            should_be_active = False

        if convention.is_active != should_be_active:
            if should_be_active:
                # Inactive convention should be activated.
                reactivations += 1
                convention.is_active = True
                updated_fields.add("is_active")
            elif convention.reactivated_at and convention.reactivated_at >= three_months_ago:
                # Active convention was reactivated recently by support, do not deactivate it even though it should
                # be according to latest ASP data.
                pass
            else:
                # Active convention should be deactivated.
                conventions_to_deactivate.append(convention)

        if updated_fields:
            convention.save(update_fields=updated_fields)

    print(f"{reactivations} conventions have been reactivated")

    if len(conventions_to_deactivate) >= CONVENTION_DEACTIVATION_THRESHOLD and timezone.localdate().month <= 6:
        # Early each year, all or most AF for the new year are missing in ASP AF data.
        # Instead of brutally deactivating all SIAE, we patiently wait until enough AF data is present.
        # While we wait, no SIAE is deactivated whatsoever.
        print(
            f"ERROR: too many conventions would be deactivated ({len(conventions_to_deactivate)} is above"
            f" threshold {CONVENTION_DEACTIVATION_THRESHOLD}) thus none will actually be!"
        )
        return

    for convention in conventions_to_deactivate:
        convention.is_active = False
        # Start the grace period now.
        convention.deactivated_at = timezone.now()
    SiaeConvention.objects.bulk_update(conventions_to_deactivate, ["is_active", "deactivated_at"], batch_size=200)

    print(f"{len(conventions_to_deactivate)} conventions have been deactivated")


def get_creatable_conventions(siret_to_siae_row, conventions_by_siae_key):
    """
    Get conventions which should be created.

    Output : list of (convention, siae) tuples.
    """
    creatable_conventions = []

    for siae in Company.objects.filter(source=Company.SOURCE_ASP, convention__isnull=True):
        if siae.siret not in siret_to_siae_row:
            # Some inactive siaes are absent in the latest ASP exports but
            # are still present in db because they have members and/or job applications.
            # We cannot build a convention object for those.
            assert not siae.is_active
            continue

        row = siret_to_siae_row[siae.siret]
        # convention is to be unique for an asp_id and a SIAE kind
        assert not SiaeConvention.objects.filter(asp_id=row.asp_id, kind=siae.kind).exists()

        convention_data = conventions_by_siae_key[(row.asp_id, siae.kind)]
        convention = SiaeConvention(
            siret_signature=row.siret_signature,
            kind=siae.kind,
            is_active=convention_data.is_active,
            asp_id=row.asp_id,
            deactivated_at=(
                None
                if convention_data.is_active
                else datetime.datetime.combine(convention_data.end_at, datetime.datetime.min.time(), datetime.UTC)
            ),
        )
        creatable_conventions.append((convention, siae))
    return creatable_conventions


def check_convention_data_consistency():
    """
    Check data consistency of conventions, not only versus siaes of ASP source,
    but also vs user created siaes.
    """
    for convention in SiaeConvention.objects.prefetch_related("siaes").all():
        # Check that each active convention has exactly one siae of ASP source.
        # Unfortunately some inactive conventions have lost their ASP siae.
        asp_siaes = [siae for siae in convention.siaes.all() if siae.source == Company.SOURCE_ASP]
        if convention.is_active:
            assert len(asp_siaes) == 1
        else:
            assert 0 <= len(asp_siaes) <= 1
            # Check that each inactive convention has a grace period start date.
            assert convention.deactivated_at is not None

        # Additional data consistency checks.
        for siae in convention.siaes.all():
            assert siae.siren == convention.siren_signature
            assert siae.kind == convention.kind

    asp_siaes_without_convention = Company.objects.filter(
        kind__in=SIAE_WITH_CONVENTION_KINDS, source=Company.SOURCE_ASP, convention__isnull=True
    ).count()
    assert asp_siaes_without_convention == 0

    user_created_siaes_without_convention = Company.objects.filter(
        kind__in=SIAE_WITH_CONVENTION_KINDS,
        source=Company.SOURCE_USER_CREATED,
        convention__isnull=True,
    ).count()
    assert user_created_siaes_without_convention == 0


def create_conventions(siret_to_siae_row, conventions_by_siae_key):
    creatable_conventions = get_creatable_conventions(siret_to_siae_row, conventions_by_siae_key)
    print(f"will create {len(creatable_conventions)} conventions")

    for convention, siae in creatable_conventions:
        assert not SiaeConvention.objects.filter(asp_id=convention.asp_id, kind=convention.kind).exists()
        convention.save()
        assert convention.siaes.count() == 0
        siae.convention = convention
        siae.save(update_fields={"convention"})
        assert convention.siaes.filter(source=Company.SOURCE_ASP).count() == 1


@transaction.atomic()
def delete_conventions():
    deletable_conventions = SiaeConvention.objects.filter(siaes__isnull=True)
    print(f"will delete {len(deletable_conventions)} conventions")
    for convention in deletable_conventions:
        # This will delete the related financial annexes as well.
        convention.delete()
