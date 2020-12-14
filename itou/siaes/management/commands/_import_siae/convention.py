"""

SiaeConvention object logic used by the import_siae.py script is gathered here.

"""
from django.utils import timezone

from itou.siaes.management.commands._import_siae.siae import does_siae_have_an_active_convention
from itou.siaes.management.commands._import_siae.vue_structure import ASP_ID_TO_SIRET_SIGNATURE, SIRET_TO_ASP_ID
from itou.siaes.models import Siae, SiaeConvention


def update_existing_conventions(dry_run):
    """
    Update existing conventions, mainly the is_active field,
    and check data integrity on the fly.
    """
    for siae in Siae.objects.filter(source=Siae.SOURCE_ASP, convention__isnull=False).select_related("convention"):
        asp_id = SIRET_TO_ASP_ID[siae.siret]
        siret_signature = ASP_ID_TO_SIRET_SIGNATURE[asp_id]

        convention = siae.convention
        assert convention.kind == siae.kind
        assert asp_id in ASP_ID_TO_SIRET_SIGNATURE
        assert convention.siren_signature == siae.siren

        # Sometimes the same siret is attached to one asp_id in one export
        # and is attached to another asp_id in the next export.
        # In other words, the siae has to be detached from its current
        # convention and be attached to a new convention.
        if convention.asp_id != asp_id:
            print(
                f"siae.id={siae.id} has changed convention from "
                f"asp_id={convention.asp_id} to asp_id={asp_id} (will be fixed)"
            )
            if not dry_run:
                # New convention will be created later by get_creatable_conventions()
                # and then attached to siae.
                siae.convention = None
                siae.save()
            continue

        # Siret_signature can change from one export to the next!
        # e.g. asp_id=4948 has changed from 81051848000027 to 81051848000019
        if convention.siret_signature != siret_signature:
            print(
                f"convention.id={convention.id} has changed siret_signature from "
                f"{convention.siret_signature} to {siret_signature} (will be fixed)"
            )
            if not dry_run:
                convention.siret_signature = siret_signature
                convention.save()

        is_active = does_siae_have_an_active_convention(siae)
        if convention.is_active != is_active:
            if not dry_run:
                convention.is_active = is_active
                if not is_active:
                    # This was a deactivation - start the grace period now.
                    convention.deactivated_at = timezone.now()
                convention.save()


def get_creatable_conventions():
    """
    Get conventions which should be created.

    Output : list of (convention, siae) tuples.
    """
    creatable_conventions = []

    for siae in Siae.objects.filter(source=Siae.SOURCE_ASP, convention__isnull=True).select_related("convention"):

        asp_id = SIRET_TO_ASP_ID.get(siae.siret)
        if asp_id not in ASP_ID_TO_SIRET_SIGNATURE:
            # Some inactive siaes are absent in the latest ASP exports but
            # are still present in db because they have members and/or job applications.
            # We cannot build a convention object for those.
            assert not siae.is_active
            continue

        siret_signature = ASP_ID_TO_SIRET_SIGNATURE.get(asp_id)

        convention = SiaeConvention(
            siret_signature=siret_signature,
            kind=siae.kind,
            is_active=does_siae_have_an_active_convention(siae),
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
        if dry_run:
            # During a dry run we might have some zero-siae conventions
            # which have not been deleted for real.
            assert len(asp_siaes) in [0, 1]
        else:
            assert len(asp_siaes) == 1

        # Additional data consistency checks.
        for siae in convention.siaes.all():
            assert siae.kind == convention.kind
            assert siae.siren == convention.siren_signature

    user_created_siaes_without_convention = Siae.objects.filter(
        kind__in=Siae.ELIGIBILITY_REQUIRED_KINDS, source=Siae.SOURCE_USER_CREATED, convention__isnull=True
    ).count()
    print(f"{user_created_siaes_without_convention} user created siaes still have no convention (technical debt)")
