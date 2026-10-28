from itou.companies.enums import (
    ProSupportReportAutonomy,
    ProSupportReportBarrier,
    ProSupportReportOrientation,
    ProSupportReportSolution,
)
from itou.companies.models import ProSupportReport
from itou.metabase.tables.utils import MetabaseTable, get_choice, get_column_from_field, get_model_field


def barrier_column(barrier, name):
    return {
        "name": name,
        "type": "boolean",
        "comment": f"Vrai si la structure a coché le frein « {barrier.label} »",
        "fn": lambda o: barrier in o.barriers,
    }


TABLE = MetabaseTable(name="bilans_accompagnement_v0")
TABLE.add_columns(
    [
        get_column_from_field(
            get_model_field(ProSupportReport, "pk"),
            name="id",
            comment="ID du bilan d’accompagnement",
        ),
        get_column_from_field(
            get_model_field(ProSupportReport, "public_id"),
            name="uid",
            comment="Identifiant universel unique du bilan, utilisé dans l’adresse de sa page sur la plateforme",
        ),
        get_column_from_field(
            get_model_field(ProSupportReport, "created_at"),
            name="date_de_création",
            comment="Date à laquelle la structure a envoyé le bilan",
        ),
        get_column_from_field(
            get_model_field(ProSupportReport, "job_seeker"),
            name="id_candidat",
            comment="ID C1 du salarié concerné par le bilan (candidats_v0.id)",
        ),
        get_column_from_field(
            get_model_field(ProSupportReport, "company"),
            name="id_structure",
            comment=(
                "ID de la structure employeuse qui a rempli le bilan (structures_v0.id), "
                "vide si la structure a été supprimée"
            ),
        ),
        get_column_from_field(
            get_model_field(ProSupportReport, "author"),
            name="id_auteur",
            comment="ID C1 du professionnel de la structure qui a rempli le bilan (utilisateurs_v0.id)",
        ),
        get_column_from_field(
            get_model_field(ProSupportReport, "notified_prescriber"),
            name="id_prescripteur_prévenu",
            comment=(
                "ID C1 du prescripteur habilité qui a reçu le bilan par mail (utilisateurs_v0.id), "
                "vide si aucun prescripteur n’a été prévenu"
            ),
        ),
        get_column_from_field(
            get_model_field(ProSupportReport, "contract"),
            name="id_contrat_asp",
            comment=(
                "ID ASP du contrat sur lequel porte le bilan, le même que dans les données ASP des contrats, "
                "vide si le contrat a disparu des données ASP ; un contrat renouvelé garde le même ID"
            ),
        ),
        get_column_from_field(
            get_model_field(ProSupportReport, "contract_end_date"),
            name="date_fin_contrat",
            comment=(
                "Date de fin du contrat au moment du bilan : date de sortie si elle était saisie à l’ASP, "
                "sinon date de fin prévue"
            ),
        ),
        barrier_column(ProSupportReportBarrier.HEALTH, "frein_santé"),
        barrier_column(ProSupportReportBarrier.MOBILITY, "frein_mobilité"),
        barrier_column(ProSupportReportBarrier.FAMILY, "frein_situation_familiale"),
        barrier_column(ProSupportReportBarrier.FINANCIAL, "frein_situation_financière"),
        barrier_column(ProSupportReportBarrier.DIGITAL, "frein_numérique"),
        barrier_column(ProSupportReportBarrier.LEGAL, "frein_administratif_ou_juridique"),
        barrier_column(ProSupportReportBarrier.LITERACY, "frein_français_ou_calcul"),
        # The free text about other barriers is left out, it may hold sensitive personal data.
        {
            "name": "autre_frein_renseigné",
            "type": "boolean",
            "comment": (
                "Vrai si la structure a décrit un autre frein ; le texte lui-même n’est pas exporté, "
                "car il peut contenir des données personnelles sensibles et confidentielles"
            ),
            "fn": lambda o: bool(o.other_barrier),
        },
        get_column_from_field(
            get_model_field(ProSupportReport, "autonomy"),
            name="autonomie",
            # Labels already end with a period, so no separator is needed.
            comment="Autonomie dans la recherche d’emploi, de 1 à 5 : "
            + " ".join(f"{autonomy.value} = {autonomy.label}" for autonomy in ProSupportReportAutonomy),
        ),
        {
            "name": "solution_envisagée",
            "type": "varchar",
            "comment": "Solution prévue après le contrat, vide si aucune n’est prévue",
            "fn": lambda o: get_choice(choices=ProSupportReportSolution.choices, key=o.solution or None),
        },
        {
            "name": "orientation_recommandée",
            "type": "varchar",
            "comment": "Orientation la plus adaptée, remplie seulement quand aucune solution n’est prévue",
            "fn": lambda o: get_choice(choices=ProSupportReportOrientation.choices, key=o.orientation or None),
        },
    ]
)
