from operator import attrgetter

from itou.job_applications.enums import JobApplicationState, Origin, RefusalReason, SenderKind
from itou.job_applications.models import JobApplication
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_choice,
    get_column_from_field,
    get_department_and_region_columns,
    get_model_field,
)
from itou.prescribers.enums import PrescriberOrganizationKind


# Reword the original SenderKind.SENDER_KIND_CHOICES
SENDER_KIND_CHOICES = (
    (SenderKind.JOB_SEEKER, "Candidat"),
    (SenderKind.PRESCRIBER, "Prescripteur"),
    (SenderKind.EMPLOYER, "Employeur"),
)


def get_job_application_origin(ja):
    if ja.sender_kind == SenderKind.PRESCRIBER:
        if ja.is_sent_by_authorized_prescriber:
            return "Prescripteur habilité"
        return "Orienteur"
    return get_choice(choices=SENDER_KIND_CHOICES, key=ja.sender_kind)


def get_job_application_detailed_origin(ja):
    """
    Builds a human readable detailed origin for job applications, e.g.
    - Employeur ACI
    - Employeur ETTI
    - Prescripteur habilité PE
    - Prescripteur habilité ML
    - Orienteur PLIE
    - Orienteur sans organisation
    - Candidat
    """
    # Start with the regular origin.
    detailed_origin = get_job_application_origin(ja)
    # Add the relevant detailed origin depending on the origin.
    if ja.sender_kind == SenderKind.EMPLOYER:
        detailed_origin += f" {ja.sender_company.kind}"
    if ja.sender_kind == SenderKind.PRESCRIBER:
        if ja.sender_prescriber_organization:
            detailed_origin += f" {ja.sender_prescriber_organization.kind}"
        else:
            detailed_origin += " sans organisation"
    return detailed_origin


def get_ja_sender_organization_pk(ja):
    if ja.sender_prescriber_organization:
        return ja.sender_prescriber_organization.pk
    return None


def get_ja_sender_organization_name(ja):
    if ja.sender_prescriber_organization:
        return ja.sender_prescriber_organization.display_name
    return None


def get_ja_sender_organization_safir(ja):
    if ja.sender_prescriber_organization:
        return ja.sender_prescriber_organization.code_safir_pole_emploi
    return None


def get_ja_sender_full_name_if_pe_or_spip(ja):
    org = ja.sender_prescriber_organization
    if org and org.kind in [PrescriberOrganizationKind.FT, PrescriberOrganizationKind.SPIP]:
        return f"{ja.sender.last_name.upper()} {ja.sender.first_name}"
    return None


TABLE = MetabaseTable(name="candidatures")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(JobApplication, "pk"), name="id"),
        {
            "name": "candidature_archivee",
            "type": "boolean",
            "comment": "Candidature archivée coté employeur",
            "fn": lambda o: bool(o.archived_at),
        },
        {
            "name": "candidature_refusée_automatiquement",
            "type": "boolean",
            "comment": "Candidature automatiquement refusée car en attente depuis plus de 2 mois",
            "fn": lambda o: bool(o.refusal_reason == RefusalReason.AUTO),
        },
        get_column_from_field(
            get_model_field(JobApplication, "created_at"), name="date_candidature", field_type="date"
        ),
        get_column_from_field(
            get_model_field(JobApplication, "hiring_start_at"), name="date_début_contrat", field_type="date"
        ),
        get_column_from_field(
            get_model_field(JobApplication, "processed_at"), name="date_traitement", field_type="date"
        ),
        {
            "name": "état",
            "type": "varchar",
            "comment": "Etat de la candidature",
            "fn": lambda o: get_choice(choices=JobApplicationState.choices, key=o.state),
        },
        {
            "name": "origine",
            "type": "varchar",
            "comment": ("Origine de la candidature (employeur, candidat, prescripteur habilité, orienteur)"),
            "fn": get_job_application_origin,
        },
        {
            "name": "origine_détaillée",
            "type": "varchar",
            "comment": (
                "Origine détaillée de la candidature "
                "(employeur EI, ACI... candidat, orienteur, prescripteur PE, ML...)"
            ),
            "fn": get_job_application_detailed_origin,
        },
        get_column_from_field(get_model_field(JobApplication, "sender_company"), name="origine_id_structure"),
        get_column_from_field(
            get_model_field(JobApplication, "origin"),
            name="parcours_de_création",
            comment=(
                "Parcours de création de la candidature"
                " (Normale, reprise de stock AI, import agrément PE, action support...)"
            ),
        ),
        {
            "name": "délai_prise_en_compte",
            "type": "interval",
            "comment": (
                "Temps écoulé rétroactivement de état nouveau à état étude si la candidature est passée par ces états"
            ),
            "fn": attrgetter("time_spent_from_new_to_processing"),
        },
        {
            "name": "délai_de_réponse",
            "type": "interval",
            "comment": (
                "Temps écoulé rétroactivement de état nouveau à état accepté"
                " ou refusé si la candidature est passée par ces états"
            ),
            "fn": attrgetter("time_spent_from_new_to_accepted_or_refused"),
        },
        {
            "name": "motif_de_refus",
            "type": "varchar",
            "comment": "Motif de refus de la candidature",
            "fn": lambda o: str(o.refusal_reason) if o.refusal_reason != "" else None,
        },
        get_column_from_field(get_model_field(JobApplication, "job_seeker"), name="id_candidat"),
        get_column_from_field(get_model_field(JobApplication, "to_company"), name="id_structure"),
        {
            "name": "type_structure",
            "type": "varchar",
            "comment": "Type de la structure destinaire de la candidature",
            "fn": attrgetter("to_company.kind"),
        },
        {
            "name": "nom_structure",
            "type": "varchar",
            "comment": "Nom de la structure destinaire de la candidature",
            "fn": attrgetter("to_company.display_name"),
        },
        {
            "name": "nom_complet_structure",
            "type": "varchar",
            "comment": "Nom complet de la structure destinaire de la candidature",
            "fn": lambda o: f"{o.to_company.kind} - ID {o.to_company_id} - {o.to_company.display_name}",
        },
    ]
)

TABLE.add_columns(
    get_department_and_region_columns(
        name_suffix="_structure",
        comment_suffix=" de la structure destinaire de la candidature",
        custom_fn=attrgetter("to_company"),
    )
)

TABLE.add_columns(
    [
        {
            "name": "id_org_prescripteur",
            "type": "integer",
            "comment": "ID de l''organisation prescriptrice",
            "fn": get_ja_sender_organization_pk,
        },
        {
            "name": "nom_org_prescripteur",
            "type": "varchar",
            "comment": "Nom de l''organisation prescriptrice",
            "fn": get_ja_sender_organization_name,
        },
        {
            "name": "safir_org_prescripteur",
            "type": "varchar",
            "comment": "SAFIR de l''organisation prescriptrice",
            "fn": get_ja_sender_organization_safir,
        },
        {
            "name": "nom_prénom_conseiller",
            "type": "varchar",
            "comment": "Nom prénom du conseiller PE ou SPIP",
            "fn": get_ja_sender_full_name_if_pe_or_spip,
        },
        {
            "name": "date_embauche",
            "type": "date",
            "comment": "Date embauche le cas échéant",
            "fn": attrgetter("transition_accepted_date"),
        },
        {
            "name": "injection_ai",
            "type": "boolean",
            "comment": "Provient des injections AI",
            "fn": lambda o: o.origin == Origin.AI_STOCK,
        },
        {
            "name": "mode_attribution_pass_iae",
            "type": "varchar",
            "comment": "Mode d''attribution du PASS IAE",
            "fn": lambda o: o.get_approval_delivery_mode_display(),
        },
        {
            "name": "type_contrat",
            "type": "varchar",
            "comment": "Type de contrat",
            "fn": lambda o: o.contract_type if o.contract_type else "",
        },
        {
            "name": "présence_de_cv",
            "type": "boolean",
            "comment": "Présence d''un CV",
            "fn": lambda o: bool(o.resume_id),
        },
    ]
)
