"""

SiaeConvention object logic used by the import_siae.py script is gathered here.

"""
from itou.siaes.management.commands._import_siae.vue_structure import EXTERNAL_ID_TO_SIRET_SIGNATURE
from itou.siaes.models import Siae, SiaeConvention


def get_creatable_conventions(dry_run):
    """
    Get conventions which should be created.

    Update existing conventions on the fly.

    Output : list of (convention, siae) tuples.
    """
    creatable_conventions = []
    for siae in Siae.objects.filter(source=Siae.SOURCE_ASP).select_related("convention"):
        if siae.convention:
            convention = siae.convention
            # These checks are needed to keep data in sync until we drop
            # those fields from the siae table.
            assert convention.kind == siae.kind
            assert convention.deactivated_at == siae.deactivated_at
            assert convention.reactivated_by == siae.reactivated_by
            assert convention.reactivated_at == siae.reactivated_at
            assert convention.asp_id == siae.external_id

            if convention.is_active != siae.is_active:
                convention.is_active = siae.is_active
                if not dry_run:
                    convention.save()

            continue

        if siae.external_id not in EXTERNAL_ID_TO_SIRET_SIGNATURE:
            # Some inactive siaes are absent in the latest ASP exports but
            # are still present in db because they have members and/or job applications.
            # We cannot build a convention object for those.
            assert not siae.is_active
            continue

        convention = SiaeConvention(
            siret_signature=EXTERNAL_ID_TO_SIRET_SIGNATURE[siae.external_id],
            kind=siae.kind,
            is_active=siae.is_active,
            deactivated_at=siae.deactivated_at,
            reactivated_by=siae.reactivated_by,
            reactivated_at=siae.reactivated_at,
            asp_id=siae.external_id,
        )
        creatable_conventions.append((convention, siae))
    return creatable_conventions


def get_deletable_conventions():
    return SiaeConvention.objects.filter(siaes__isnull=True)
