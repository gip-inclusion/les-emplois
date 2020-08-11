from django.utils.translation import gettext_lazy as _

from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.metabase.management.commands._utils import anonymize, get_choice, get_department_and_region_columns


# Reword the original JobApplication.SENDER_KIND_CHOICES
SENDER_KIND_CHOICES = (
    (JobApplication.SENDER_KIND_JOB_SEEKER, _("Candidature autonome")),
    (JobApplication.SENDER_KIND_PRESCRIBER, _("Candidature via prescripteur")),
    (JobApplication.SENDER_KIND_SIAE_STAFF, _("Auto-prescription")),
)


def get_job_application_sub_type(ja):
    """
    Builds a human readable sub category for job applications, e.g.
    - Auto-prescription ACI
    - Auto-prescription ETTI
    - Candidature via prescripteur PE
    - Candidature via prescripteur ML
    - Candidature via prescripteur sans organisation
    - Candidature autonome
    """
    # Start with the regular type.
    sub_type = get_choice(choices=SENDER_KIND_CHOICES, key=ja.sender_kind)
    # Add the relevant sub type depending on the type.
    if ja.sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF:
        sub_type += f" {ja.sender_siae.kind}"
    if ja.sender_kind == JobApplication.SENDER_KIND_PRESCRIBER:
        if ja.sender_prescriber_organization:
            sub_type += f" {ja.sender_prescriber_organization.kind}"
        else:
            sub_type += " sans organisation"
    return sub_type


def _get_ja_time_spent_in_transition(ja, logs):
    assert len(logs) in [0, 1]
    if len(logs) == 1:
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
        "name": "type",
        "type": "varchar",
        "comment": ("Type de la candidature (auto-prescription, candidature autonome, candidature via prescripteur)"),
        "lambda": lambda o: get_choice(choices=SENDER_KIND_CHOICES, key=o.sender_kind),
    },
    {
        "name": "sous_type",
        "type": "varchar",
        "comment": (
            "Sous-type de la candidature (auto-prescription par EI, ACI..."
            " candidature autonome, candidature via prescripteur PE, ML...)"
        ),
        "lambda": get_job_application_sub_type,
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
] + get_department_and_region_columns(
    name_suffix="_structure",
    comment_suffix=" de la structure destinaire de la candidature",
    custom_lambda=lambda o: o.to_siae,
)
