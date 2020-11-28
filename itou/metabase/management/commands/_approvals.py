from datetime import datetime

from django.conf import settings

from itou.approvals.models import Approval, PoleEmploiApproval
from itou.metabase.management.commands._utils import get_department_and_region_columns, get_hiring_siae


# from itou.prescribers.models import PrescriberOrganization


POLE_EMPLOI_APPROVAL_MINIMUM_START_DATE = datetime(2018, 1, 1)

# # Preload association for best performance and to avoid having to make
# # PoleEmploiApproval.pe_structure_code a foreign key.
# CODE_SAFIR_TO_PE_ORG = {
#     org.code_safir_pole_emploi: org
#     for org in PrescriberOrganization.objects.filter(code_safir_pole_emploi__isnull=False).all()
# }


def get_siae_from_approval(approval):
    if isinstance(approval, PoleEmploiApproval):
        return None
    assert isinstance(approval, Approval)
    return get_hiring_siae(approval.user)


def get_siae_or_pe_org_from_approval(approval):
    if isinstance(approval, Approval):
        return get_siae_from_approval(approval)
    assert isinstance(approval, PoleEmploiApproval)
    # code_safir = approval.pe_structure_code
    # pe_org = CODE_SAFIR_TO_PE_ORG.get(code_safir)
    # return pe_org
    return None


def get_approval_type(approval):
    """
    Build a human readable category for approvals and PE approvals.
    """
    if isinstance(approval, Approval):
        if approval.number.startswith(settings.ASP_ITOU_PREFIX):
            return f"PASS IAE ({settings.ASP_ITOU_PREFIX})"
        else:
            return f"Agrément PE via ITOU (non {settings.ASP_ITOU_PREFIX})"
    elif isinstance(approval, PoleEmploiApproval):
        if len(approval.number) == 12:
            return "Agrément PE"
        elif len(approval.number) == 15:
            suffix = approval.number[12]
            return f"{PoleEmploiApproval.Suffix[suffix].label} PE"
        else:
            raise ValueError("Unexpected PoleEmploiApproval.number length")
    else:
        raise ValueError("Unknown approval type.")


TABLE_COLUMNS = [
    {"name": "type", "type": "varchar", "comment": "FIXME", "lambda": get_approval_type},
    {"name": "date_début", "type": "date", "comment": "Date de début", "lambda": lambda o: o.start_at},
    {"name": "date_fin", "type": "date", "comment": "Date de fin", "lambda": lambda o: o.end_at},
    {"name": "durée", "type": "interval", "comment": "Durée", "lambda": lambda o: o.end_at - o.start_at},
    # -------- Field not ready for code review yet --------
    # # The rigorous date would be:
    # # $ job_application.approval_number_sent_at
    # # however some approvals have two or more job_applications
    # # with different approval_number_sent_at values.
    # # Thus we simply use approval.created_at here.
    # {
    #     "name": "date_de_délivrance",
    #     "type": "date",
    #     "comment": "Date de délivrance si PASS IAE",
    #     "lambda": lambda o: o.created_at if isinstance(o, Approval) else None,
    # },
    # ------------------------------------------------------
    {
        "name": "id_structure",
        "type": "integer",
        "comment": "ID structure qui a embauché si PASS IAE",
        "lambda": lambda o: getattr(get_siae_from_approval(o), "id", None),
    },
    {
        "name": "type_structure",
        "type": "varchar",
        "comment": "Type de la structure qui a embauché si PASS IAE",
        "lambda": lambda o: getattr(get_siae_from_approval(o), "kind", None),
    },
    {
        "name": "siret_structure",
        "type": "varchar",
        "comment": "SIRET de la structure qui a embauché si PASS IAE",
        "lambda": lambda o: getattr(get_siae_from_approval(o), "siret", None),
    },
    {
        "name": "nom_structure",
        "type": "varchar",
        "comment": "Nom de la structure qui a embauché si PASS IAE",
        "lambda": lambda o: getattr(get_siae_from_approval(o), "display_name", None),
    },
] + get_department_and_region_columns(
    name_suffix="_structure_ou_org_pe",
    comment_suffix=(" de la structure qui a embauché si PASS IAE ou du PE qui a délivré l agrément si Agrément PE"),
    custom_lambda=get_siae_or_pe_org_from_approval,
)
