from django import forms
from django.utils.translation import gettext as _

from itou.eligibility.models import EligibilityDiagnosis


# Besoins d'accompagnement.
BARRIERS = [
    {
        "value": "faire_face_a_des_difficultes_administratives_ou_juridiques",
        "label": _("Faire face à des difficultés administratives ou juridiques"),
        "items": [
            {
                "value": "connaitre_les_voies_de_recours_face_a_une_discrimination",
                "label": _("Connaitre les voies de recours face à une discrimination"),
            },
            {
                "value": "prendre_en_compte_une_problematique_judiciaire",
                "label": _("Prendre en compte une problématique judiciaire"),
            },
            {
                "value": "regler_un_probleme_administratif_ou_juridique",
                "label": _("Régler un problème administratif ou juridique"),
            },
        ],
    },
    {
        "value": "faire_face_a_des_difficultes_financieres",
        "label": _("Faire face à des difficultés financières"),
        "items": [
            {
                "value": "acceder_a_des_services_gratuits",
                "label": _("Accéder à des services gratuits"),
            },
            {
                "value": "beneficier_daides_financieres_hors_celles_de_pole_emploi",
                "label": _(
                    "Bénéficier d'aides financières (hors celles de Pôle emploi)"
                ),
            },
            {
                "value": "etre_aide_pour_gerer_son_budget",
                "label": _("Etre aidé pour gérer son budget"),
            },
            {
                "value": "faire_face_a_un_endettement",
                "label": _("Faire face à un endettement"),
            },
            {
                "value": "obtenir_une_aide_alimentaire",
                "label": _("Obtenir une aide alimentaire"),
            },
        ],
    },
    {
        "value": "se_deplacer",
        "label": _("Se déplacer"),
        "items": [
            {
                "value": "disposer_dun_vehicule_en_etat_de_marche",
                "label": _("Disposer d'un véhicule en état de marche"),
            },
            {
                "value": "faire_le_point_sur_sa_mobilite",
                "label": _("Faire le point sur sa mobilité"),
            },
            {
                "value": "passer_son_permis_de_conduire",
                "label": _("Passer son permis de conduire"),
            },
            {
                "value": "trouver_une_solution_de_transport",
                "label": _("Trouver une solution de transport"),
            },
        ],
    },
    {
        "value": "se_loger",
        "label": _("Se loger"),
        "items": [
            {
                "value": "se_maintenir_dans_son_logement",
                "label": _("Se maintenir dans son logement"),
            },
            {"value": "se_mettre_a_labri", "label": _("Se mettre à l'abri")},
            {"value": "trouver_un_logement", "label": _("Trouver un logement")},
        ],
    },
    {
        "value": "se_soigner",
        "label": _("Se soigner"),
        "items": [
            {"value": "faire_un_bilan_de_sante", "label": _("Faire un bilan de santé")},
            {
                "value": "obtenir_une_couverture_sociale",
                "label": _("Obtenir une couverture sociale"),
            },
            {
                "value": "rencontrer_un_medecincentre_de_soins",
                "label": _("Rencontrer un médecin/centre de soins"),
            },
            {
                "value": "rencontrer_un_psychologue",
                "label": _("Rencontrer un psychologue"),
            },
        ],
    },
    {
        "value": "sortir_de_lisolement",
        "label": _("Sortir de l'isolement"),
        "items": [
            {
                "value": "acceder_aux_ressources_internet_et_telephonie_mobile",
                "label": _("Accéder aux ressources Internet et téléphonie mobile"),
            },
            {
                "value": "creer_des_liens_sociaux_rompre_avec_lisolement",
                "label": _("Créer des liens sociaux, rompre avec l'isolement"),
            },
            {
                "value": "participer_a_des_activites_sociales_et_culturelles",
                "label": _("Participer à des activités sociales et culturelles"),
            },
        ],
    },
    {
        "value": "maitriser_les_savoirs_de_base",
        "label": _("Maitriser les savoirs de base"),
        "items": [
            {
                "value": "sortir_dune_situation_dillettrisme_danalphabetisme",
                "label": _("Sortir d'une situation d'illettrisme, d'analphabétisme"),
            },
            {
                "value": "suivre_une_formation_francais_langue_etrangere",
                "label": _("Suivre une formation Français Langue Étrangère"),
            },
            {"value": "savoir_compter", "label": _("Savoir compter")},
        ],
    },
    {
        "value": "surmonter_des_contraintes_familiales",
        "label": _("Surmonter des contraintes familiales"),
        "items": [
            {
                "value": "etre_accompagne_dans_la_perte_dun_proche",
                "label": _("Etre accompagné dans la perte d'un proche"),
            },
            {
                "value": "etre_aide_dans_la_parentalite_et_la_prevention",
                "label": _("Etre aidé dans la parentalité et la prévention"),
            },
            {
                "value": "faire_face_a_des_difficulte_educatives",
                "label": _("Faire face à des difficulté éducatives"),
            },
            {
                "value": "faire_face_a_la_prise_en_charge_dune_personne_dependante",
                "label": _("Faire face à la prise en charge d'une personne dépendante"),
            },
            {"value": "faire_garder_son_enfant", "label": _("Faire garder son enfant")},
            {
                "value": "se_faire_aider_en_cas_de_conflit_familial_et_ou_separation",
                "label": _(
                    "Se faire aider en cas de conflit familial et / ou séparation"
                ),
            },
        ],
    },
]

# Critères administratifs.
ADMINISTRATIVE_CRITERIA = [
    {
        "value": "criteres_administratifs_de_niveau_1",
        "label": _("Critères administratifs de niveau 1"),
        "items": [
            {
                "value": "beneficiaire_du_rsa",
                "label": _("Bénéficiaire du RSA"),
                "written_proof": _("Attestation RSA"),
                "help": _("Revenu de solidarité active"),
                "url": None,
            },
            {
                "value": "allocataire_ass",
                "label": _("Allocataire ASS"),
                "written_proof": _("Attestation ASS"),
                "help": _("Allocation de solidarité spécifique"),
                "url": None,
            },
            {
                "value": "allocataire_aah",
                "label": _("Allocataire AAH"),
                "written_proof": _("Attestation AAH"),
                "help": _("Allocation aux adultes handicapés"),
                "url": None,
            },
            {
                "value": "detld_24_mois",
                "label": _("DETLD (+24 mois)"),
                "written_proof": _("Attestation Pôle emploi"),
                "help": _(
                    "Demandeur d'emploi de très longue durée (inscrit à Pôle emploi)"
                ),
                "url": None,
            },
            {
                "value": "personne_sans_emploi_de_tres_longue_duree_24_mois",
                "label": _("Personne sans emploi de très longue durée (+24 mois)"),
                "written_proof": None,
                "help": _("Non inscrit à Pôle emploi sur la période"),
                "url": None,
            },
            {
                "value": "personne_sous_main_justice",
                "label": _("Personne sous-main justice"),
                "written_proof": _("Attestation SPIP, PJJ"),
                "help": _(""),
                "url": None,
            },
            {
                "value": "allocataire_ata",
                "label": _("Allocataire ATA"),
                "written_proof": _("Attestation ATA"),
                "help": _("Allocation temporaire d'attente"),
                "url": None,
            },
        ],
    },
    {
        "value": "criteres_administratifs_de_niveau_2",
        "label": _("Critères administratifs de niveau 2"),
        "items": [
            {
                "value": "niveau_detude_infra_iv",
                "label": _("Niveau d'étude infra IV"),
                "written_proof": None,
                "help": _(""),
                "url": "https://www.insee.fr/fr/metadonnees/definition/c1076",
            },
            {
                "value": "senior_50_ans",
                "label": _("Senior (+50 ans)"),
                "written_proof": _("Pièce d'identité"),
                "help": None,
                "url": None,
            },
            {
                "value": "jeunes_26_ans_neet",
                "label": _("Jeunes (-26 ans) NEET"),
                "written_proof": _("Pièce d'identité"),
                "help": None,
                "url": None,
            },
            {
                "value": "sortant_de_lase",
                "label": _("Sortant de l'ASE"),
                "written_proof": _("Attestation ASE"),
                "help": _("Aide sociale à l'enfance"),
                "url": None,
            },
            {
                "value": "deld_12_mois",
                "label": _("DELD (+12 mois)"),
                "written_proof": _("Attestation Pôle emploi"),
                "help": _("Demandeur d'emploi de longue durée (inscrit à Pôle emploi)"),
                "url": None,
            },
            {
                "value": "personne_sans_emploi_de_longue_duree_12_mois",
                "label": _("Personne sans emploi de longue durée (+12 mois)"),
                "written_proof": None,
                "help": _("Non inscrit à Pôle emploi sur la période"),
                "url": None,
            },
            {
                "value": "travailleur_handicape",
                "label": _("Travailleur handicapé"),
                "written_proof": _("Attestation reconnaissance qualité TH"),
                "help": None,
                "url": None,
            },
            {
                "value": "personnes_ayant_fait_lobjet_dun_licenciement_economique",
                "label": _("Personnes ayant fait l'objet d'un licenciement économique"),
                "written_proof": None,
                "help": _(""),
                "url": None,
            },
            {
                "value": "parent_isole",
                "label": _("Parent isolé"),
                "written_proof": _("Attestation CAF"),
                "help": _(""),
                "url": None,
            },
            {
                "value": "sans_hebergement_ou_personne_hebergee",
                "label": _("Sans hébergement ou personne hébergée"),
                "written_proof": _("Attestation sur l'honneur"),
                "help": _(""),
                "url": None,
            },
            {
                "value": "primo_arrivant",
                "label": _("Primo arrivant"),
                "written_proof": None,
                "help": _(""),
                "url": None,
            },
            {
                "value": "resident_zrr",
                "label": _("Résident ZRR"),
                "written_proof": _("Justificatif de domicile"),
                "help": _("Zone de revitalisation rurale"),
                "url": "https://www.data.gouv.fr/fr/datasets/zones-de-revitalisation-rurale-zrr/",
            },
            {
                "value": "resident_qpv",
                "label": _("Résident QPV"),
                "written_proof": _("Justificatif de domicile"),
                "help": _("Quartier prioritaire de la politique de la ville"),
                "url": "https://sig.ville.gouv.fr/",
            },
        ],
    },
]


class EligibilityForm(forms.Form):

    BARRIERS = BARRIERS
    ADMINISTRATIVE_CRITERIA = ADMINISTRATIVE_CRITERIA
