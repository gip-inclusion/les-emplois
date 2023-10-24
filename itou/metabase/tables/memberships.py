from itou.companies.models import SiaeMembership
from itou.institutions.models import InstitutionMembership
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field
from itou.prescribers.models import PrescriberMembership


def get_field(name):
    return InstitutionMembership._meta.get_field(name)


TABLE = MetabaseTable(name="collaborations")
TABLE.add_columns(
    [
        # Do not add an `id` field as it would *not* be unique among various kinds of memberships.
        get_column_from_field(get_field("user_id"), name="id_utilisateur"),
        get_column_from_field(get_field("is_admin"), name="administrateur"),
        {
            "name": "id_structure",
            "type": "integer",
            "comment": "ID structure",
            "fn": lambda o: o.siae_id if isinstance(o, SiaeMembership) else None,
        },
        {
            "name": "id_organisation",
            "type": "integer",
            "comment": "ID organisation prescripteur",
            "fn": lambda o: o.organization_id if isinstance(o, PrescriberMembership) else None,
        },
        {
            "name": "id_institution",
            "type": "integer",
            "comment": "ID institution",
            "fn": lambda o: o.institution_id if isinstance(o, InstitutionMembership) else None,
        },
    ]
)
