"""

SiaeConvention object logic used by the import_siae.py script is gathered here.

"""
from django.utils import timezone

from itou.siaes.management.commands._import_siae.siae import does_siae_have_an_active_convention
from itou.siaes.management.commands._import_siae.vue_structure import (
    EXTERNAL_ID_TO_SIRET_SIGNATURE,
    SIRET_TO_EXTERNAL_ID,
)
from itou.siaes.models import Siae, SiaeConvention


def update_existing_conventions(dry_run):
    """
    Update existing conventions, mainly the is_active field,
    and check data integrity on the fly.
    """
    for siae in Siae.objects.filter(source=Siae.SOURCE_ASP, convention__isnull=False).select_related("convention"):
        external_id = SIRET_TO_EXTERNAL_ID[siae.siret]
        siret_signature = EXTERNAL_ID_TO_SIRET_SIGNATURE[external_id]

        convention = siae.convention
        assert convention.kind == siae.kind
        assert convention.asp_id == external_id
        assert external_id in EXTERNAL_ID_TO_SIRET_SIGNATURE
        assert convention.siret_signature == siret_signature
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
        external_id = SIRET_TO_EXTERNAL_ID[siae.siret]
        siret_signature = EXTERNAL_ID_TO_SIRET_SIGNATURE.get(external_id)

        if external_id not in EXTERNAL_ID_TO_SIRET_SIGNATURE:
            # Some inactive siaes are absent in the latest ASP exports but
            # are still present in db because they have members and/or job applications.
            # We cannot build a convention object for those.
            assert not siae.is_active
            continue

        convention = SiaeConvention(
            siret_signature=siret_signature,
            kind=siae.kind,
            is_active=does_siae_have_an_active_convention(siae),
            asp_id=external_id,
        )
        creatable_conventions.append((convention, siae))
    return creatable_conventions


def get_deletable_conventions():
    return SiaeConvention.objects.filter(siaes__isnull=True)
