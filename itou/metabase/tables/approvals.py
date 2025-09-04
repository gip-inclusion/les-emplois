import functools

from django.conf import settings

from itou.approvals.enums import Origin
from itou.approvals.models import Approval
from itou.companies.models import Company
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_column_from_field,
    get_department_and_region_columns,
    get_model_field,
    hash_content,
)


@functools.cache
def get_companies_map():
    return {c.pk: c for c in Company.objects.only("kind", "siret", "name", "brand", "department")}


def get_company_from_approval(approval):
    return get_companies_map().get(approval.last_hiring_company_pk)


def get_approval_type(approval):
    """
    Build a human readable category for approvals and PE approvals.
    """
    if approval.number.startswith(settings.ASP_ITOU_PREFIX):
        return f"PASS IAE ({settings.ASP_ITOU_PREFIX})"

    return f"Agrément PE via ITOU (non {settings.ASP_ITOU_PREFIX})"


TABLE = MetabaseTable(name="pass_agréments")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(Approval, "pk"), name="id"),
        {"name": "type", "type": "varchar", "comment": "Type", "fn": get_approval_type},
        get_column_from_field(get_model_field(Approval, "start_at"), name="date_début", field_type="date"),
        get_column_from_field(get_model_field(Approval, "end_at"), name="date_fin", field_type="date"),
        {"name": "durée", "type": "interval", "comment": "Durée", "fn": lambda o: o.end_at - o.start_at},
        {
            "name": "id_candidat",
            "type": "integer",
            "comment": "ID C1 du candidat",
            "fn": lambda o: o.user_id if isinstance(o, Approval) else None,
        },
        {
            "name": "id_structure",
            "type": "integer",
            "comment": "ID structure qui a embauché si PASS IAE",
            "fn": lambda o: getattr(get_company_from_approval(o), "id", None),
        },
        {
            "name": "type_structure",
            "type": "varchar",
            "comment": "Type de la structure qui a embauché si PASS IAE",
            "fn": lambda o: getattr(get_company_from_approval(o), "kind", None),
        },
        {
            "name": "siret_structure",
            "type": "varchar",
            "comment": "SIRET de la structure qui a embauché si PASS IAE",
            "fn": lambda o: getattr(get_company_from_approval(o), "siret", None),
        },
        {
            "name": "nom_structure",
            "type": "varchar",
            "comment": "Nom de la structure qui a embauché si PASS IAE",
            "fn": lambda o: getattr(get_company_from_approval(o), "display_name", None),
        },
    ]
)

TABLE.add_columns(
    get_department_and_region_columns(
        name_suffix="_structure_ou_org_pe",
        comment_suffix=(
            " de la structure qui a embauché si PASS IAE ou du PE qui a délivré l agrément si Agrément PE"
        ),
        custom_fn=get_company_from_approval,
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
            "comment": "Version obfusquée du PASS IAE ou d'agrément",
            "fn": lambda o: hash_content(o.number),
        },
    ]
)
