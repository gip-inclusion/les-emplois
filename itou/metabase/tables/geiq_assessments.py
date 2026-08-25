"""
Tables feeding the "Bilans d'exécution GEIQ" Metabase dashboard.

Two tables are exported instead of duplicating the contracts for every assessment field:
 - `geiq_assessments`: one row per assessment, holding the amounts negotiated and granted by the
   DDETS/DREETS (i.e. montants conventionnés et accordés).
 - `geiq_contracts`: one row per contract, holding the potential allowance of the contract and whether it
   was presented by the GEIQ and/or granted by the DDETS/DREETS.

"""

from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS, department_from_postcode
from itou.geiq_assessments.enums import AllowanceJustificationReason, AllowanceRefusalReason
from itou.geiq_assessments.models import Assessment, Employee, EmployeeContract
from itou.metabase.tables.utils import MetabaseTable, get_choice, get_column_from_field, get_model_field


def get_department_and_region_columns(department_fn, *, comment_suffix=""):
    """
    Same columns as `utils.get_department_and_region_columns` but the department is computed by `department_fn`
    instead of being read on a `department` attribute.
    """
    return [
        {
            "name": "department",
            "type": "varchar",
            "comment": f"Département{comment_suffix}",
            "fn": department_fn,
        },
        {
            "name": "department_name",
            "type": "varchar",
            "comment": f"Nom complet du département{comment_suffix}",
            "fn": lambda o: DEPARTMENTS.get(department_fn(o)),
        },
        {
            "name": "region",
            "type": "varchar",
            "comment": f"Région{comment_suffix}",
            "fn": lambda o: DEPARTMENT_TO_REGION.get(department_fn(o)),
        },
    ]


def get_assessment_department(assessment):
    return department_from_postcode(assessment.label_geiq_post_code) or None


def get_conventionned_departments(assessment):
    # An assessment may be conventionned by several institutions (e.g. a DDETS and its DREETS).
    return sorted({institution.department for institution in assessment.conventionned_institutions()})


AssessmentsTable = MetabaseTable(name="geiq_assessments")
AssessmentsTable.add_columns(
    [
        get_column_from_field(get_model_field(Assessment, "pk"), name="id"),
        {
            "name": "campaign_year",
            "type": "integer",
            "comment": "Année sur laquelle porte le bilan d’exécution",
            "fn": lambda o: o.campaign.year,
        },
        {
            "name": "state",
            "type": "varchar",
            "comment": "État du bilan d’exécution",
            "fn": lambda o: o.state.title,
        },
        get_column_from_field(get_model_field(Assessment, "label_geiq_id"), name="label_geiq_id"),
        get_column_from_field(get_model_field(Assessment, "label_geiq_name"), name="label_geiq_name"),
        get_column_from_field(get_model_field(Assessment, "label_geiq_post_code"), name="label_geiq_post_code"),
    ]
    + get_department_and_region_columns(get_assessment_department, comment_suffix=" du GEIQ principal")
    + [
        {
            "name": "conventionned_institutions_departments",
            "type": "varchar[]",
            "comment": "Départements des DDETS/DREETS ayant conventionné le GEIQ",
            "fn": get_conventionned_departments,
        },
        get_column_from_field(get_model_field(Assessment, "with_main_geiq"), name="with_main_geiq"),
        {
            "name": "antenna_nb",
            "type": "integer",
            "comment": "Nombre d’antennes concernées par le bilan d’exécution",
            "fn": lambda o: len(o.label_antennas or []),
        },
        get_column_from_field(get_model_field(Assessment, "employee_nb"), name="employee_nb"),
        # Amounts decided by the DDETS/DREETS. To be compared with potential amounts computed from `geiq_contracts`.
        get_column_from_field(get_model_field(Assessment, "convention_amount"), name="convention_amount"),
        get_column_from_field(get_model_field(Assessment, "granted_amount"), name="granted_amount"),
        get_column_from_field(get_model_field(Assessment, "advance_amount"), name="advance_amount"),
        get_column_from_field(get_model_field(Assessment, "created_at"), name="created_at"),
        get_column_from_field(
            get_model_field(Assessment, "contracts_selection_validated_at"),
            name="contracts_selection_validated_at",
        ),
        get_column_from_field(get_model_field(Assessment, "submitted_at"), name="submitted_at"),
        get_column_from_field(
            get_model_field(Assessment, "grants_selection_validated_at"), name="grants_selection_validated_at"
        ),
        get_column_from_field(get_model_field(Assessment, "decision_validated_at"), name="decision_validated_at"),
        get_column_from_field(get_model_field(Assessment, "reviewed_at"), name="reviewed_at"),
        get_column_from_field(get_model_field(Assessment, "final_reviewed_at"), name="final_reviewed_at"),
        get_column_from_field(
            get_model_field(Assessment, "reviewed_by_institution"), name="reviewed_by_institution_id"
        ),
        get_column_from_field(
            get_model_field(Assessment, "final_reviewed_by_institution"), name="final_reviewed_by_institution_id"
        ),
    ]
)


ContractsTable = MetabaseTable(name="geiq_contracts")
ContractsTable.add_columns(
    [
        get_column_from_field(get_model_field(EmployeeContract, "pk"), name="id"),
        {
            "name": "assessment_id",
            "type": "uuid",
            "comment": "Identifiant du bilan d’exécution",
            "fn": lambda o: o.employee.assessment_id,
        },
        get_column_from_field(get_model_field(EmployeeContract, "employee"), name="employee_id"),
        {
            "name": "campaign_year",
            "type": "integer",
            "comment": "Année sur laquelle porte le bilan d’exécution",
            "fn": lambda o: o.employee.assessment.campaign.year,
        },
    ]
    + get_department_and_region_columns(
        lambda o: o.antenna_department() or None, comment_suffix=" de l’antenne portant le contrat"
    )
    + [
        get_column_from_field(get_model_field(EmployeeContract, "start_at"), name="start_at"),
        get_column_from_field(get_model_field(EmployeeContract, "planned_end_at"), name="planned_end_at"),
        get_column_from_field(get_model_field(EmployeeContract, "end_at"), name="end_at"),
        get_column_from_field(
            get_model_field(EmployeeContract, "nb_days_in_campaign_year"), name="nb_days_in_campaign_year"
        ),
        # A contract is "présenté" when the GEIQ asks for its allowance, and "retenu" when the DDETS/DREETS
        # grants it (which is only meaningful once the assessment has been definitely reviewed).
        get_column_from_field(get_model_field(EmployeeContract, "allowance_requested"), name="allowance_requested"),
        get_column_from_field(get_model_field(EmployeeContract, "allowance_granted"), name="allowance_granted"),
        {
            "name": "allowance_amount",
            "type": "integer",
            "comment": "Aide potentielle du salarié (0, 814 ou 1400 €)",
            "fn": lambda o: o.employee.allowance_amount,
        },
        {
            "name": "allowance_request_justification_reason",
            "type": "varchar",
            "comment": "Motif dérogatoire justifiant la demande d’aide (GEIQ)",
            "fn": lambda o: get_choice(
                choices=AllowanceJustificationReason.choices, key=o.allowance_request_justification_reason or None
            ),
        },
        {
            "name": "allowance_refusal_reason",
            "type": "varchar",
            "comment": "Motif de refus de l’aide (DDETS/DREETS)",
            "fn": lambda o: get_choice(choices=AllowanceRefusalReason.choices, key=o.allowance_refusal_reason or None),
        },
        {
            "name": "allowance_granted_previous_year",
            "type": "boolean",
            "comment": str(get_model_field(Employee, "allowance_granted_previous_year").verbose_name),
            "fn": lambda o: o.employee.allowance_granted_previous_year,
        },
    ]
)
