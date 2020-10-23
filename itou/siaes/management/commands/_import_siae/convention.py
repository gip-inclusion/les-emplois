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
        # Siret_signature can change from one export to the next!
        # e.g. asp_id=4948 has changed from 81051848000027 to 81051848000019
        if convention.siret_signature != siret_signature:
            if not dry_run:
                convention.siret_signature = siret_signature
                convention.save()

        assert convention.kind == siae.kind
        assert convention.asp_id == asp_id
        assert asp_id in ASP_ID_TO_SIRET_SIGNATURE
        assert convention.siren_signature == siae.siren

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

    Update existing conventions on the fly.

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
