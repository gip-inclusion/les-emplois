from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.metabase.management.commands._utils import get_address_columns, get_choice, get_first_membership_join_date
from itou.siaes.models import Siae


def get_siae_first_join_date(siae):
    return get_first_membership_join_date(memberships=siae.siaemembership_set)


TABLE_COLUMNS = (
    [
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
    + get_address_columns(comment_suffix=" de la structure")
    + [
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
            "name": "total_auto_prescriptions",
            "type": "integer",
            "comment": "Nombre de candidatures de source employeur dont la structure est destinataire",
            # We have to do all this in python to benefit from prefetch_related.
            "lambda": lambda o: len(
                [
                    ja
                    for ja in o.job_applications_received.all()
                    if ja.sender_kind == JobApplication.SENDER_KIND_SIAE_STAFF
                ]
            ),
        },
        {
            "name": "total_candidatures_autonomes",
            "type": "integer",
            "comment": "Nombre de candidatures de source candidat dont la structure est destinataire",
            # We have to do all this in python to benefit from prefetch_related.
            "lambda": lambda o: len(
                [
                    ja
                    for ja in o.job_applications_received.all()
                    if ja.sender_kind == JobApplication.SENDER_KIND_JOB_SEEKER
                ]
            ),
        },
        {
            "name": "total_candidatures_via_prescripteur",
            "type": "integer",
            "comment": "Nombre de candidatures de source prescripteur dont la structure est destinataire",
            # We have to do all this in python to benefit from prefetch_related.
            "lambda": lambda o: len(
                [
                    ja
                    for ja in o.job_applications_received.all()
                    if ja.sender_kind == JobApplication.SENDER_KIND_PRESCRIBER
                ]
            ),
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
        {"name": "longitude", "type": "float", "comment": "Longitude", "lambda": lambda o: o.longitude},
        {"name": "latitude", "type": "float", "comment": "Latitude", "lambda": lambda o: o.latitude},
    ]
)
