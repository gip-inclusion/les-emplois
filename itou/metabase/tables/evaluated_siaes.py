from itou.metabase.tables.utils import MetabaseTable, get_column_from_field
from itou.siae_evaluations.enums import EvaluatedSiaeState
from itou.siae_evaluations.models import EvaluatedSiae


def get_field(name):
    return EvaluatedSiae._meta.get_field(name)


def get_state(evaluated_siae):
    # For backward compatibility, continue to output NOTIFICATION_PENDING state
    # until the dashboards could be adapted (we might want to also output the notified_at column)
    # TODO(xfernandez): return to lambda o:o.state once it isn't necessary anymore
    state = evaluated_siae.state
    if state == EvaluatedSiaeState.REFUSED and evaluated_siae.evaluation_is_final and not evaluated_siae.notified_at:
        return "NOTIFICATION_PENDING"
    return state


TABLE = MetabaseTable(name="cap_structures")
TABLE.add_columns(
    [
        get_column_from_field(get_field("id"), name="id"),
        get_column_from_field(get_field("evaluation_campaign_id"), name="id_cap_campagne"),
        get_column_from_field(get_field("siae_id"), name="id_structure"),
        {
            "name": "état",
            "type": "varchar",
            "comment": "Etat du contrôle de la structure",
            "fn": get_state,
        },
        get_column_from_field(get_field("reviewed_at"), name="date_contrôle"),
        get_column_from_field(get_field("final_reviewed_at"), name="date_définitive_contrôle"),
    ]
)
