"""

SiaeConvention object logic used by the import_siae.py script is gathered here.

"""
from collections import defaultdict

from django.utils import timezone

from itou.siaes.management.commands._import_siae.siae import does_siae_have_an_active_convention
from itou.siaes.management.commands._import_siae.vue_structure import ASP_ID_TO_SIRET_SIGNATURE, SIRET_TO_ASP_ID
from itou.siaes.models import Siae, SiaeConvention


# In general we deactivate conventions which should be deactivated,
# but some timings are tricky like the beginning of each year.
# For example in ASP dataset of Jan 4 2021, no structure had any valid
# AF for 2021 yet, which means we would have deactivated 4013 conventions o_O
# In these cases we temporarily no longer deactivate any convention until
# AF data catches up.
DEACTIVATE_CONVENTIONS = False


def update_existing_conventions(dry_run):
    """
    Update existing conventions, mainly the is_active field,
    and check data integrity on the fly.
    """
    deactivations = 0
    deactivations_by_kind = defaultdict(int)  # 0 by default
    reactivations = 0
    for siae in Siae.objects.filter(source=Siae.SOURCE_ASP, convention__isnull=False).select_related("convention"):
        if siae.siret not in SIRET_TO_ASP_ID:
            # This can happen in a dry run only, when a siae should have changed
            # its SIRET during update_siret_and_auth_email_of_existing_siaes()
            # but did not yet due to dry run.
            assert dry_run
            print(f"ignored unknown siret of siae.id={siae.id} due to dry run")
            continue
        asp_id = SIRET_TO_ASP_ID[siae.siret]
        siret_signature = ASP_ID_TO_SIRET_SIGNATURE[asp_id]

        convention = siae.convention
        assert convention.kind == siae.kind
        assert asp_id in ASP_ID_TO_SIRET_SIGNATURE
        assert convention.siren_signature == siae.siren

        # Sometimes the same siret is attached to one asp_id in one export and to another asp_id in the next export.
        # In other words, the siae convention asp_id has changed and should be updated.
        # Ideally this should never happen because the asp_id is supposed to be an immutable id of the structure
        # in ASP data, but one can only hope.
        if convention.asp_id != asp_id:
            print(
                f"convention.id={convention.id} has changed asp_id from "
                f"{convention.asp_id} to {asp_id} (will be updated)"
            )
            assert not SiaeConvention.objects.filter(asp_id=asp_id, kind=siae.kind).exists()
            if not dry_run:
                convention.asp_id = asp_id
                convention.save()
            continue

        # Siret_signature can change from one export to the next!
        # e.g. asp_id=4948 has changed from 81051848000027 to 81051848000019
        if convention.siret_signature != siret_signature:
            print(
                f"convention.id={convention.id} has changed siret_signature from "
                f"{convention.siret_signature} to {siret_signature} (will be updated)"
            )
            if not dry_run:
                convention.siret_signature = siret_signature
                convention.save()

        should_be_active = does_siae_have_an_active_convention(siae)
        if convention.is_active != should_be_active:
            if should_be_active:
                reactivations += 1
                if not dry_run:
                    convention.is_active = True
                    convention.save()
            else:
                deactivations += 1
                deactivations_by_kind[convention.kind] += 1
                if DEACTIVATE_CONVENTIONS and not dry_run:
                    convention.is_active = False
                    # Start the grace period now.
                    convention.deactivated_at = timezone.now()
                    convention.save()

    print(f"{reactivations} conventions will be reactivated")

    total = SiaeConvention.objects.count()
    if DEACTIVATE_CONVENTIONS:
        print(f"{deactivations} of {total} conventions will be deactivated")
        assert deactivations <= 400  # Break if too many deactivations would occur.
    else:
        print(f"{deactivations} of {total} conventions would have been deactivated but will *not* be")

    # Text in french ready to be copy/pasted to the DGEFP/ASP.
    print("=== BEGINNING OF FRENCH TEXT FOR DGEFP/ASP ===")
    pct_value = round(100 * deactivations / total, 1)
    print(f"{deactivations} des {total} SIAE ({pct_value}%) n'ont pas d'AF 2021 à ce jour")
    for kind, _ in Siae.KIND_CHOICES:
        total = SiaeConvention.objects.filter(kind=kind).count()
        if total >= 1:  # Skip GEIQ etc and avoid division by zero.
            pct_value = round(100 * deactivations_by_kind[kind] / total, 1)
            print(f"{deactivations_by_kind[kind]} des {total} {kind} ({pct_value}%) n'ont pas d'AF 2021 à ce jour")
    print("=== END OF FRENCH TEXT FOR DGEFP/ASP ===")


def get_creatable_conventions():
    """
    Get conventions which should be created.

    Output : list of (convention, siae) tuples.
    """
    creatable_conventions = []

    for siae in Siae.objects.filter(source=Siae.SOURCE_ASP, convention__isnull=True):

        asp_id = SIRET_TO_ASP_ID.get(siae.siret)
        if asp_id not in ASP_ID_TO_SIRET_SIGNATURE:
            # Some inactive siaes are absent in the latest ASP exports but
            # are still present in db because they have members and/or job applications.
            # We cannot build a convention object for those.
            assert not siae.is_active
            continue

        siret_signature = ASP_ID_TO_SIRET_SIGNATURE.get(asp_id)

        if DEACTIVATE_CONVENTIONS:
            is_active = does_siae_have_an_active_convention(siae)
        else:
            # At the beginning of each year, when AFs of the new year are not there yet, we temporarily
            # consider all new conventions as active by default even though they do not have a valid AF yet.
            is_active = True

        assert not SiaeConvention.objects.filter(asp_id=asp_id, kind=siae.kind).exists()

        convention = SiaeConvention(
            siret_signature=siret_signature,
            kind=siae.kind,
            is_active=is_active,
            asp_id=asp_id,
        )
        creatable_conventions.append((convention, siae))
    return creatable_conventions


def get_deletable_conventions():
    return SiaeConvention.objects.filter(siaes__isnull=True)


def check_convention_data_consistency(dry_run):
    """
    Check data consistency of conventions, not only versus siaes of ASP source,
    but also vs user created siaes.
    """
    for convention in SiaeConvention.objects.prefetch_related("siaes").all():
        # Check that each convention has exactly one siae of ASP source.
        asp_siaes = [siae for siae in convention.siaes.all() if siae.source == Siae.SOURCE_ASP]

        if not dry_run:
            assert len(asp_siaes) == 1

        if not convention.is_active:
            # Check that each inactive convention has a grace period start date.
            assert convention.deactivated_at is not None

        # Additional data consistency checks.
        for siae in convention.siaes.all():
            assert siae.siren == convention.siren_signature
            if siae.is_kind_aciphc and convention.is_kind_aci:
                assert siae.is_source_user_created
                # Sometimes our staff manually changes an existing ACI antenna's kind from ACI to ACIPHC and forgets
                # to detach the ACI convention.
                if not dry_run:
                    siae.convention = None
                    siae.save()
            else:
                assert siae.kind == convention.kind

    asp_siaes_without_convention = Siae.objects.filter(
        kind__in=Siae.ASP_MANAGED_KINDS, source=Siae.SOURCE_ASP, convention__isnull=True
    ).count()
    assert asp_siaes_without_convention == 0

    user_created_siaes_without_convention = Siae.objects.filter(
        kind__in=Siae.ASP_MANAGED_KINDS,
        source=Siae.SOURCE_USER_CREATED,
        convention__isnull=True,
    ).count()
    print(f"{user_created_siaes_without_convention} user created siaes still have no convention (technical debt)")
