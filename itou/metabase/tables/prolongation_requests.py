from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import ProlongationRequest
from itou.metabase.tables.utils import (
    MetabaseTable,
    get_choice,
    get_column_from_field,
    get_common_prolongation_columns,
)


def get_field(name):
    return ProlongationRequest._meta.get_field(name)


TABLE = MetabaseTable(name="demandes_de_prolongation")
TABLE.add_columns(
    get_common_prolongation_columns(get_field_fn=get_field)
    + [
        {
            "name": "id_prolongation",
            "type": "integer",
            "comment": "ID C1 de la prolongation",
            # Trick to access a reverse OneToOneField without a related_name.
            # See:
            # - https://stackoverflow.com/questions/57881833/django-reverse-onetoonefield-matching-without-related-name
            # - https://stackoverflow.com/questions/25944968/check-if-a-onetoone-relation-exists-in-django
            "fn": lambda o: o.prolongation.pk if hasattr(o, "prolongation") else None,
        },
        {
            "name": "état",
            "type": "varchar",
            "comment": "Etat de la demande",
            "fn": lambda o: get_choice(choices=ProlongationRequestStatus.choices, key=o.status),
        },
        {
            "name": "motif_de_refus",
            "type": "varchar",
            "comment": "Motif de refus de la demande",
            "fn": lambda o: o.deny_information.reason if hasattr(o, "deny_information") else None,
        },
        {
            "name": "date_de_demande",
            "type": "date",
            "comment": "Date de la demande",
            "fn": lambda o: o.created_at.date(),
        },
        get_column_from_field(get_field("processed_at"), name="date_traitement"),
        get_column_from_field(get_field("processed_by_id"), name="id_utilisateur_traitant"),
        get_column_from_field(get_field("reminder_sent_at"), name="date_envoi_rappel"),
    ]
)
