from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.metabase.management.commands._utils import anonymize, get_choice, get_department_and_region_columns


# Reword the original JobApplication.SENDER_KIND_CHOICES
SENDER_KIND_CHOICES = (
    (JobApplication.SENDER_KIND_JOB_SEEKER, "Candidat"),
    (JobApplication.SENDER_KIND_PRESCRIBER, "Prescripteur"),
    (JobApplication.SENDER_KIND_SIAE_STAFF, "Employeur"),
)


def get_job_application_origin(ja):
    if ja.sender_kind == JobApplication.SENDER_KIND_PRESCRIBER:
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
    if ja.sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF:
        detailed_origin += f" {ja.sender_siae.kind}"
    if ja.sender_kind == JobApplication.SENDER_KIND_PRESCRIBER:
        if ja.sender_prescriber_organization:
            detailed_origin += f" {ja.sender_prescriber_organization.kind}"
        else:
            detailed_origin += " sans organisation"
    return detailed_origin


def get_ja_sender_organization_name(ja):
    if ja.sender_prescriber_organization:
        return ja.sender_prescriber_organization.display_name
    return None


def get_ja_sender_organization_safir(ja):
    if ja.sender_prescriber_organization:
        return ja.sender_prescriber_organization.code_safir_pole_emploi
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
        log
        for log in ja.logs.all()
        if log.to_state in [JobApplicationWorkflow.STATE_ACCEPTED, JobApplicationWorkflow.STATE_REFUSED]
    ]
    return _get_ja_time_spent_in_transition(ja, logs)


def get_ja_hiring_date(ja):
    # We have to do all this in python to benefit from prefetch_related.
    logs = [log for log in ja.logs.all() if log.transition == JobApplicationWorkflow.TRANSITION_ACCEPT]
    assert len(logs) in [0, 1]
    if len(logs) == 1:
        transition_timestamp = logs[0].timestamp
        return transition_timestamp
    return None


TABLE_COLUMNS = [
    {
        "name": "id_anonymisé",
        "type": "varchar",
        "comment": "ID anonymisé de la candidature",
        "lambda": lambda o: anonymize(o.id, salt="job_application.id"),
    },
    {
        "name": "date_candidature",
        "type": "date",
        "comment": "Date de la candidature",
        "lambda": lambda o: o.created_at,
    },
    {
        "name": "état",
        "type": "varchar",
        "comment": "Etat de la candidature",
        "lambda": lambda o: get_choice(choices=JobApplicationWorkflow.STATE_CHOICES, key=o.state),
    },
    {
        "name": "origine",
        "type": "varchar",
        "comment": ("Origine de la candidature (employeur, candidat, prescripteur habilité, orienteur)"),
        "lambda": get_job_application_origin,
    },
    {
        "name": "origine_détaillée",
        "type": "varchar",
        "comment": (
            "Origine détaillée de la candidature (employeur EI, ACI..." " candidat, orienteur, prescripteur PE, ML...)"
        ),
        "lambda": get_job_application_detailed_origin,
    },
    {
        "name": "délai_prise_en_compte",
        "type": "interval",
        "comment": (
            "Temps écoulé rétroactivement de état nouveau à état étude" " si la candidature est passée par ces états"
        ),
        "lambda": get_ja_time_spent_from_new_to_processing,
    },
    {
        "name": "délai_de_réponse",
        "type": "interval",
        "comment": (
            "Temps écoulé rétroactivement de état nouveau à état accepté"
            " ou refusé si la candidature est passée par ces états"
        ),
        "lambda": get_ja_time_spent_from_new_to_accepted_or_refused,
    },
    {
        "name": "motif_de_refus",
        "type": "varchar",
        "comment": "Motif de refus de la candidature",
        "lambda": lambda o: get_choice(choices=JobApplication.REFUSAL_REASON_CHOICES, key=o.refusal_reason),
    },
    {
        "name": "id_candidat_anonymisé",
        "type": "varchar",
        "comment": "ID anonymisé du candidat",
        "lambda": lambda o: anonymize(o.job_seeker_id, salt="job_seeker.id"),
    },
    {
        "name": "id_structure",
        "type": "integer",
        "comment": "ID de la structure destinaire de la candidature",
        "lambda": lambda o: o.to_siae_id,
    },
    {
        "name": "type_structure",
        "type": "varchar",
        "comment": "Type de la structure destinaire de la candidature",
        "lambda": lambda o: o.to_siae.kind,
    },
    {
        "name": "nom_structure",
        "type": "varchar",
        "comment": "Nom de la structure destinaire de la candidature",
        "lambda": lambda o: o.to_siae.display_name,
    },
    {
        "name": "nom_org_prescripteur",
        "type": "varchar",
        "comment": "Nom de l''organisation prescriptrice",
        "lambda": get_ja_sender_organization_name,
    },
    {
        "name": "safir_org_prescripteur",
        "type": "varchar",
        "comment": "SAFIR de l''organisation prescriptrice",
        "lambda": get_ja_sender_organization_safir,
    },
]

TABLE_COLUMNS += get_department_and_region_columns(
    name_suffix="_structure",
    comment_suffix=" de la structure destinaire de la candidature",
    custom_lambda=lambda o: o.to_siae,
)

TABLE_COLUMNS += [
    {
        "name": "date_embauche",
        "type": "date",
        "comment": "Date embauche le cas échéant",
        "lambda": get_ja_hiring_date,
    },
]
