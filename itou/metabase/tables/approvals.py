import functools
from datetime import datetime

from django.conf import settings

from itou.approvals.enums import Origin
from itou.approvals.models import Approval, PoleEmploiApproval
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_column_from_field,
    get_department_and_region_columns,
    get_hiring_company,
    hash_content,
)
from itou.prescribers.models import PrescriberOrganization


POLE_EMPLOI_APPROVAL_MINIMUM_START_DATE = datetime(2018, 1, 1)


def get_field(name):
    return Approval._meta.get_field(name)


@functools.cache
def get_code_safir_to_pe_org():
    # Preload association for best performance and to avoid having to make
    # PoleEmploiApproval.pe_structure_code a foreign key.
    return {
        org.code_safir_pole_emploi: org
        for org in PrescriberOrganization.objects.filter(code_safir_pole_emploi__isnull=False).all()
    }


def get_company_from_approval(approval):
    if isinstance(approval, PoleEmploiApproval):
        return None
    assert isinstance(approval, Approval)
    if not approval.user.is_job_seeker:
        # Sometimes we have incorrect data where a user has an approval, thus should be a job seeker,
        # but actually is a prescriber or an employer.
        # We ignore this error here and instead report it in the final `report_data_inconsistencies` method.
        return None
    return get_hiring_company(approval.user)


def get_company_or_pe_org_from_approval(approval):
    if isinstance(approval, Approval):
        return get_company_from_approval(approval)
    assert isinstance(approval, PoleEmploiApproval)
    code_safir = approval.pe_structure_code
    pe_org = get_code_safir_to_pe_org().get(code_safir)
    return pe_org


def get_approval_type(approval):
    """
    Build a human readable category for approvals and PE approvals.
    """
    if isinstance(approval, Approval):
        if approval.number.startswith(settings.ASP_ITOU_PREFIX):
            return f"PASS IAE ({settings.ASP_ITOU_PREFIX})"

        return f"Agrément PE via ITOU (non {settings.ASP_ITOU_PREFIX})"
    elif isinstance(approval, PoleEmploiApproval):
        if len(approval.number) == 12:
            return "Agrément PE"
        elif len(approval.number) == 15:
            suffix = approval.number[12]
            return f"{PoleEmploiApproval.Suffix[suffix].label} PE"

        raise ValueError("Unexpected PoleEmploiApproval.number length")

    raise ValueError("Unknown approval type.")


TABLE = MetabaseTable(name="pass_agréments")
TABLE.add_columns(
    [
        get_column_from_field(get_field("id"), name="id"),
        {"name": "type", "type": "varchar", "comment": "Type", "fn": get_approval_type},
        {"name": "date_début", "type": "date", "comment": "Date de début", "fn": lambda o: o.start_at},
        {"name": "date_fin", "type": "date", "comment": "Date de fin", "fn": lambda o: o.end_at},
        {"name": "durée", "type": "interval", "comment": "Durée", "fn": lambda o: o.end_at - o.start_at},
        {
            "name": "id_candidat",
            "type": "integer",
            "comment": "ID C1 du candidat",
            "fn": lambda o: o.user_id if isinstance(o, Approval) else None,
        },
        {
            # TODO @dejafait : eventually drop this obsolete field
            "name": "id_candidat_anonymisé",
            "type": "varchar",
            "comment": "ID anonymisé du candidat",
            "fn": lambda o: hash_content(o.user_id) if isinstance(o, Approval) else None,
        },
        {
            "name": "id_structure",
            "type": "integer",
            "comment": "ID structure qui a embauché si PASS IAE",
            "fn": lambda o: getattr(get_company_from_approval(o), "id", None),
        },
        {
            "name": "type_structure",
            "type": "varchar",
            "comment": "Type de la structure qui a embauché si PASS IAE",
            "fn": lambda o: getattr(get_company_from_approval(o), "kind", None),
        },
        {
            "name": "siret_structure",
            "type": "varchar",
            "comment": "SIRET de la structure qui a embauché si PASS IAE",
            "fn": lambda o: getattr(get_company_from_approval(o), "siret", None),
        },
        {
            "name": "nom_structure",
            "type": "varchar",
            "comment": "Nom de la structure qui a embauché si PASS IAE",
            "fn": lambda o: getattr(get_company_from_approval(o), "display_name", None),
        },
    ]
)

TABLE.add_columns(
    get_department_and_region_columns(
        name_suffix="_structure_ou_org_pe",
        comment_suffix=(
            " de la structure qui a embauché si PASS IAE ou du PE qui a délivré l agrément si Agrément PE"
        ),
        custom_fn=get_company_or_pe_org_from_approval,
    )
)

TABLE.add_columns(
    [
        {
            "name": "injection_ai",
            "type": "boolean",
            "comment": "Provient des injections AI",
            "fn": lambda o: o.origin == Origin.AI_STOCK if isinstance(o, Approval) else False,
        },
        {
            "name": "hash_numéro_pass_iae",
            "type": "varchar",
            "comment": "Version obfusquée du PASS IAE ou d'agrément",
            "fn": lambda o: hash_content(o.number),
        },
    ]
)
