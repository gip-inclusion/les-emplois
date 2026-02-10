from itou.users.enums import UserKind
from itou.utils.export import Format


def with_format(format, func):
    func.export_format = format
    return func


def get_libelle(item):
    if not item:  # item can be a dict or False
        return ""
    return item.get("libelle", "")


def oui_non(value):
    if value is None:
        return ""
    return "Oui" if value else "Non"


def _get_employee_criteria(contract):
    criteria = []
    for criterion in contract.employee.other_data.get("statuts_prioritaire", []):
        level = criterion["niveau"]
        libelle = criterion["libelle"]
        annexe = "Annexe 1" if level == 99 else f"Annexe 2 Niveau {level}"
        criteria.append(f"{libelle} ({annexe})")
    return "\n".join(criteria)


EMPLOYEE_CONTRACT_XLSX_FORMAT = {
    "Nom candidat": with_format(Format.TEXT, lambda contract: contract.employee.last_name),
    "Prénom candidat": with_format(Format.TEXT, lambda contract: contract.employee.first_name),
    "Sexe": with_format(Format.TEXT, lambda contract: contract.employee.sex_display()),
    "Date de naissance": with_format(Format.DATE, lambda contract: contract.employee.birthdate),
    "Prescripteur": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.employee.other_data.get("prescripteur", {}))
    ),
    "Autre prescripteur": with_format(
        Format.TEXT, lambda contract: contract.employee.other_data.get("autre_prescripteur", "")
    ),
    "Montant de l’aide potentielle": with_format(Format.INTEGER, lambda contract: contract.employee.allowance_amount),
    "Critères public prioritaire": with_format(Format.TEXT, _get_employee_criteria),
    "Précisions critères public prioritaire": with_format(
        Format.TEXT, lambda contract: contract.employee.other_data.get("precision_status_prio", "")
    ),
    "Nom de la structure": with_format(
        Format.TEXT,
        lambda contract: (
            "Siège"
            if contract.other_data.get("antenne", {}).get("id") == 0
            else contract.other_data.get("antenne", {}).get("nom")
        ),
    ),
    "Département de la structure": with_format(Format.TEXT, lambda contract: contract.antenna_department()),
    "Type de contrat": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("nature_contrat", {}))
    ),
    "Temps plein": with_format(Format.TEXT, lambda contract: oui_non(contract.other_data.get("is_temps_plein"))),
    "Date de début": with_format(Format.DATE, lambda contract: contract.start_at),
    "Date de fin prévisionnelle": with_format(Format.DATE, lambda contract: contract.planned_end_at),
    "Date de fin effective": with_format(Format.DATE, lambda contract: contract.end_at),
    "Nombre de jours réalisés au total": with_format(Format.INTEGER, lambda contract: contract.duration().days),
    "Nombre de jours réalisés en N-1": with_format(Format.INTEGER, lambda contract: contract.nb_days_in_campaign_year),
    "Poste occupé": with_format(Format.TEXT, lambda contract: contract.other_data.get("metier_prepare", "")),
    "Secteur d’activité": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("secteur_activite", {}).get("nom", "")
    ),
    "Durée hebdomadaire du contrat (heures)": with_format(
        Format.FLOAT, lambda contract: contract.other_data.get("nb_heure_hebdo", "")
    ),
    "Précision sur la nature du contrat": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("nature_contrat_autre_precision", "")
    ),
    "Détail sur la nature du contrat": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("nature_contrat_precision", "")
    ),
    "Contrat professionnel expérimental": with_format(
        Format.TEXT, lambda contract: oui_non(contract.other_data.get("is_contrat_pro_experimental"))
    ),
    "Contrat signé dans le cadre d’une clause d’insertion": with_format(
        Format.TEXT, lambda contract: oui_non(contract.other_data.get("signer_cadre_clause_insertion"))
    ),
    "Raison d’une signature d’un contrat hors alternance": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("hors_alternance_precision", "")
    ),
    "Multi mises à disposition": with_format(
        Format.TEXT, lambda contract: oui_non(contract.other_data.get("is_multi_mad"))
    ),
    "Rémunération supérieure aux minima réglementaires": with_format(
        Format.TEXT, lambda contract: oui_non(contract.other_data.get("is_remuneration_superieur_minima"))
    ),
    "Nombre d’entreprises": with_format(
        Format.INTEGER, lambda contract: contract.other_data.get("mad_nb_entreprises", 0)
    ),
    "Heures de suivi de l’évaluation des compétences prévues": with_format(
        Format.FLOAT, lambda contract: contract.other_data.get("heures_suivi_evaluation_competences_geiq_prevues", "")
    ),
    "Mise en situation professionnelle": with_format(
        Format.TEXT, lambda contract: oui_non(contract.other_data.get("mise_en_situation_professionnelle_bool"))
    ),
    "Détail sur la mise en situation professionnelle": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("mise_en_situation_professionnelle_precision", "")
    ),
    "Type de mise en situation professionnelle": with_format(
        Format.TEXT,
        lambda contract: get_libelle(contract.other_data.get("mise_en_situation_professionnelle", {})),
    ),
    "Préqualifications": with_format(
        Format.TEXT,
        lambda contract: "\n".join(contract.employee.get_prior_actions()),
    ),
    "Niveau de qualification": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.employee.other_data.get("qualification", {}))
    ),
    "Titulaire d’un bac général": with_format(
        Format.TEXT, lambda contract: oui_non(contract.employee.other_data.get("is_bac_general"))
    ),
    "Qualification visée": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("qualification_visee", {}))
    ),
    "Type de qualification visée": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("type_qualification_visee", {}))
    ),
    "Qualification obtenue": with_format(
        Format.TEXT, lambda contract: oui_non(contract.other_data.get("is_qualification_obtenue"))
    ),
    "Niveau de qualification obtenue": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("qualification_obtenu", {}))
    ),
    "Type de qualification obtenue": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("type_qualification_obtenu", {}))
    ),
    "Formation complémentaire": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("formation_complementaire", "")
    ),
    "Formation complémentaire prévue": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("formation_complementaire_prevue", "")
    ),
    "Heures de formation prévues": with_format(
        Format.FLOAT, lambda contract: contract.other_data.get("heures_formation_prevue", "")
    ),
    "Heures de formation réalisées": with_format(
        Format.FLOAT, lambda contract: contract.other_data.get("heures_formation_realisee", "")
    ),
    "Nom de l’organisme de formation": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("organisme_formation", "")
    ),
    "Modalité de formation": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("modalite_formation", {}))
    ),
    "Emploi de sortie": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("emploi_sorti", {}))
    ),
    "Détail sur l’emploi de sortie": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("emploi_sorti_precision_text", "")
    ),
    "Précision sur l’emploi de sortie": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("emploi_sorti_precision", {}))
    ),
    "Métier correspondant": with_format(
        Format.TEXT, lambda contract: contract.other_data.get("metier_correspondant", "")
    ),
    "CDD/CDI refusé": with_format(Format.TEXT, lambda contract: oui_non(contract.other_data.get("is_refus_cdd_cdi"))),
    "Date de rupture anticipée": with_format(
        Format.DATE,
        lambda contract: contract.end_at if contract.end_at and contract.end_at < contract.planned_end_at else None,
    ),
    "Type de rupture anticipée": with_format(Format.TEXT, lambda contract: contract.rupture_kind_display()),
    "Situation post-contrat": with_format(
        Format.TEXT, lambda contract: get_libelle(contract.other_data.get("emploi_sorti", {}))
    ),
}


def export_format_for_user_kind(user_kind):
    user_fields = {}
    if user_kind == UserKind.EMPLOYER:
        user_fields["Demande d’aide"] = with_format(
            Format.TEXT, lambda contract: oui_non(contract.allowance_requested)
        )
    elif user_kind == UserKind.LABOR_INSPECTOR:
        user_fields["Éligible à l’aide"] = with_format(
            Format.TEXT, lambda contract: oui_non(contract.allowance_granted)
        )
    return {**EMPLOYEE_CONTRACT_XLSX_FORMAT, **user_fields}


def serialize_employee_contract(contracts_qs, export_format):
    return [tuple(serializer(contract) for serializer in export_format.values()) for contract in contracts_qs]
