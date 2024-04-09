from itou.job_applications.enums import JobApplicationState, Origin, SenderKind
from itou.job_applications.models import JobApplicationWorkflow
from itou.metabase.tables.utils import MetabaseTable, get_choice, get_department_and_region_columns
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
    if org and org.kind in [PrescriberOrganizationKind.PE, PrescriberOrganizationKind.SPIP]:
        return f"{ja.sender.last_name.upper()} {ja.sender.first_name}"
    return None


def _get_ja_time_spent_in_transition(ja, logs):
    # Some job applications have duplicate transitions.
    # E.g. job application id:4db81292-ff51-4950-a8dc-cf7c9f94c67e
    # has 2 almost identical "refuse" transitions.
    # In which case we consider any of the duplicates.
    if len(logs) >= 1:
        new_timestamp = ja.created_at
        transition_timestamp = logs[0].timestamp
        assert transition_timestamp > new_timestamp
        time_spent_in_transition = transition_timestamp - new_timestamp
        return time_spent_in_transition
    return None


def get_ja_time_spent_from_new_to_processing(ja):
    # Find the new=>processing transition log.
    # We have to do all this in python to benefit from prefetch_related.
    logs = [log for log in ja.logs.all() if log.transition == JobApplicationWorkflow.TRANSITION_PROCESS]
    return _get_ja_time_spent_in_transition(ja, logs)


def get_ja_time_spent_from_new_to_accepted_or_refused(ja):
    # Find the *=>accepted or *=>refused transition log.
    # We have to do all this in python to benefit from prefetch_related.
    logs = [
        log for log in ja.logs.all() if log.to_state in [JobApplicationState.ACCEPTED, JobApplicationState.REFUSED]
    ]
    return _get_ja_time_spent_in_transition(ja, logs)


def get_ja_hiring_date(ja):
    # We have to do all this in python to benefit from prefetch_related.
    logs = [log for log in ja.logs.all() if log.transition == JobApplicationWorkflow.TRANSITION_ACCEPT]
    # Job applications can be accepted more than once (e.g. 401b0ee1-d977-4338-b436-77839a9ed12c).
    if len(logs) >= 1:
        transition_timestamp = logs[0].timestamp
        return transition_timestamp
    return None


TABLE = MetabaseTable(name="candidatures")
TABLE.add_columns(
    [
        {
            "name": "id",
            "type": "uuid",
            "comment": "ID C1 de la candidature",
            "fn": lambda o: o.pk,
        },
        {
            "name": "date_candidature",
            "type": "date",
            "comment": "Date de la candidature",
            "fn": lambda o: o.created_at,
        },
        {
            "name": "date_début_contrat",
            "type": "date",
            "comment": "Date de début du contrat",
            "fn": lambda o: o.hiring_start_at,
        },
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
        {
            "name": "parcours_de_création",
            "type": "varchar",
            "comment": (
                "Parcours de création de la candidature "
                "(Normale, reprise de stock AI, import agrément PE, action support...)"
            ),
            "fn": lambda o: o.origin,
        },
        {
            "name": "délai_prise_en_compte",
            "type": "interval",
            "comment": (
                "Temps écoulé rétroactivement de état nouveau à état étude si la candidature est passée par ces états"
            ),
            "fn": get_ja_time_spent_from_new_to_processing,
        },
        {
            "name": "délai_de_réponse",
            "type": "interval",
            "comment": (
                "Temps écoulé rétroactivement de état nouveau à état accepté"
                " ou refusé si la candidature est passée par ces états"
            ),
            "fn": get_ja_time_spent_from_new_to_accepted_or_refused,
        },
        {
            "name": "motif_de_refus",
            "type": "varchar",
            "comment": "Motif de refus de la candidature",
            "fn": lambda o: o.get_refusal_reason_display() if o.refusal_reason != "" else None,
        },
        {
            "name": "id_candidat",
            "type": "integer",
            "comment": "ID C1 du candidat",
            "fn": lambda o: o.job_seeker_id,
        },
        {
            "name": "id_structure",
            "type": "integer",
            "comment": "ID de la structure destinaire de la candidature",
            "fn": lambda o: o.to_company_id,
        },
        {
            "name": "type_structure",
            "type": "varchar",
            "comment": "Type de la structure destinaire de la candidature",
            "fn": lambda o: o.to_company.kind,
        },
        {
            "name": "nom_structure",
            "type": "varchar",
            "comment": "Nom de la structure destinaire de la candidature",
            "fn": lambda o: o.to_company.display_name,
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
        custom_fn=lambda o: o.to_company,
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
            "fn": get_ja_hiring_date,
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
            "comment": "Mode d''attribution du PASS IAE",
            "fn": lambda o: o.get_approval_delivery_mode_display(),
        },
        {
            "name": "type_contrat",
            "type": "varchar",
            "comment": "Type de contrat",
            "fn": lambda o: o.contract_type if o.contract_type else "",
        },
    ]
)
