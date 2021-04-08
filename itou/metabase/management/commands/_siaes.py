from django.utils import timezone

from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.metabase.management.commands._utils import (
    get_address_columns,
    get_choice,
    get_establishment_is_active_column,
    get_establishment_last_login_date_column,
    get_first_membership_join_date,
)
from itou.siaes.models import Siae


ONE_MONTH_AGO = timezone.now() - timezone.timedelta(days=30)


def get_siae_first_join_date(siae):
    return get_first_membership_join_date(memberships=siae.siaemembership_set)


def get_siae_last_ja_transition_date(siae):
    timestamps = []
    for ja in siae.job_applications_received.all():
        ja_timestamps = [
            log.timestamp for log in ja.logs.all() if log.to_state != JobApplicationWorkflow.STATE_OBSOLETE
        ]
        if len(ja_timestamps) >= 1:
            timestamps.append(max(ja_timestamps))
    return max(timestamps, default=None)


def get_siae_last_month_job_applications(siae):
    return [ja for ja in siae.job_applications_received.all() if ja.created_at > ONE_MONTH_AGO]


def get_siae_last_month_hirings(siae):
    return [
        ja
        for ja in siae.job_applications_received.all()
        if ja.created_at > ONE_MONTH_AGO and ja.state == JobApplicationWorkflow.STATE_ACCEPTED
    ]


TABLE_COLUMNS = [
    {"name": "id", "type": "integer", "comment": "ID de la structure", "lambda": lambda o: o.id},
    {"name": "nom", "type": "varchar", "comment": "Nom de la structure", "lambda": lambda o: o.display_name},
    {
        "name": "description",
        "type": "varchar",
        "comment": "Description de la structure",
        "lambda": lambda o: o.description,
    },
    {
        "name": "type",
        "type": "varchar",
        "comment": "Type de structure (EI, ETTI, ACI, GEIQ etc..)",
        "lambda": lambda o: o.kind,
    },
    {"name": "siret", "type": "varchar", "comment": "SIRET de la structure", "lambda": lambda o: o.siret},
    {
        "name": "source",
        "type": "varchar",
        "comment": "Source des données de la structure",
        "lambda": lambda o: get_choice(choices=Siae.SOURCE_CHOICES, key=o.source),
    },
]

TABLE_COLUMNS += get_address_columns(comment_suffix=" de la structure")

TABLE_COLUMNS += [
    {
        "name": "date_inscription",
        "type": "date",
        "comment": "Date inscription du premier compte employeur",
        "lambda": get_siae_first_join_date,
    },
    {
        "name": "total_membres",
        "type": "integer",
        "comment": "Nombre de comptes employeur rattachés à la structure",
        "lambda": lambda o: o.members.count(),
    },
    {
        "name": "total_candidatures",
        "type": "integer",
        "comment": "Nombre de candidatures dont la structure est destinataire",
        "lambda": lambda o: len(o.job_applications_received.all()),
    },
    {
        "name": "total_candidatures_30j",
        "type": "integer",
        "comment": "Nombre de candidatures dans les 30 jours glissants dont la structure est destinataire",
        "lambda": lambda o: len(get_siae_last_month_job_applications(o)),
    },
    {
        "name": "total_embauches",
        "type": "integer",
        "comment": "Nombre de candidatures en état accepté dont la structure est destinataire",
        # We have to do all this in python to benefit from prefetch_related.
        "lambda": lambda o: len(
            [ja for ja in o.job_applications_received.all() if ja.state == JobApplicationWorkflow.STATE_ACCEPTED]
        ),
    },
    {
        "name": "total_embauches_30j",
        "type": "integer",
        "comment": (
            "Nombre de candidatures en état accepté dans les 30 jours glissants " "dont la structure est destinataire"
        ),
        "lambda": lambda o: len(get_siae_last_month_hirings(o)),
    },
    {
        "name": "taux_conversion_30j",
        "type": "float",
        "comment": "Taux de conversion des candidatures en embauches dans les 30 jours glissants",
        "lambda": lambda o: round(
            1.0 * len(get_siae_last_month_hirings(o)) / len(get_siae_last_month_job_applications(o))
            if get_siae_last_month_job_applications(o)
            else 0.0,
            2,
        ),
    },
    {
        "name": "total_auto_prescriptions",
        "type": "integer",
        "comment": "Nombre de candidatures de source employeur dont la structure est destinataire",
        # We have to do all this in python to benefit from prefetch_related.
        "lambda": lambda o: len(
            [ja for ja in o.job_applications_received.all() if ja.sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF]
        ),
    },
    {
        "name": "total_candidatures_autonomes",
        "type": "integer",
        "comment": "Nombre de candidatures de source candidat dont la structure est destinataire",
        # We have to do all this in python to benefit from prefetch_related.
        "lambda": lambda o: len(
            [ja for ja in o.job_applications_received.all() if ja.sender_kind == JobApplication.SENDER_KIND_JOB_SEEKER]
        ),
    },
    {
        "name": "total_candidatures_via_prescripteur",
        "type": "integer",
        "comment": "Nombre de candidatures de source prescripteur dont la structure est destinataire",
        # We have to do all this in python to benefit from prefetch_related.
        "lambda": lambda o: len(
            [ja for ja in o.job_applications_received.all() if ja.sender_kind == JobApplication.SENDER_KIND_PRESCRIBER]
        ),
    },
    {
        "name": "total_candidatures_non_traitées",
        "type": "integer",
        "comment": "Nombre de candidatures en état nouveau dont la structure est destinataire",
        # We have to do all this in python to benefit from prefetch_related.
        "lambda": lambda o: len(
            [ja for ja in o.job_applications_received.all() if ja.state == JobApplicationWorkflow.STATE_NEW]
        ),
    },
    {
        "name": "total_candidatures_en_étude",
        "type": "integer",
        "comment": "Nombre de candidatures en état étude dont la structure est destinataire",
        # We have to do all this in python to benefit from prefetch_related.
        "lambda": lambda o: len(
            [ja for ja in o.job_applications_received.all() if ja.state == JobApplicationWorkflow.STATE_PROCESSING]
        ),
    },
]

TABLE_COLUMNS += get_establishment_last_login_date_column()

TABLE_COLUMNS += get_establishment_is_active_column()

TABLE_COLUMNS += [
    {
        "name": "date_dernière_évolution_candidature",
        "type": "date",
        "comment": "Date de dernière évolution candidature sauf passage obsolète",
        "lambda": get_siae_last_ja_transition_date,
    },
    {
        "name": "total_fiches_de_poste_actives",
        "type": "integer",
        "comment": "Nombre de fiches de poste actives de la structure",
        "lambda": lambda o: len([jd for jd in o.job_description_through.all() if jd.is_active]),
    },
    {
        "name": "total_fiches_de_poste_inactives",
        "type": "integer",
        "comment": "Nombre de fiches de poste inactives de la structure",
        "lambda": lambda o: len([jd for jd in o.job_description_through.all() if not jd.is_active]),
    },
    {"name": "longitude", "type": "float", "comment": "Longitude", "lambda": lambda o: o.longitude},
    {"name": "latitude", "type": "float", "comment": "Latitude", "lambda": lambda o: o.latitude},
]
