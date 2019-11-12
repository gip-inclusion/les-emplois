import json

from functools import lru_cache

from django import forms
from django.utils.translation import gettext as _

from itou.eligibility.models import EligibilityDiagnosis


class EligibilityForm(forms.Form):
    """
    This form works closely with the EligibilityDiagnosis model
    (even if it's not a ModelForm).

    Its data is stored in DB as JSON because the choices are NOT
    guaranteed to stay the same over time.

    A hardcoded versioning system of the form is under consideration
    with the VERSION class attribute and the version number in the
    form and template filenames.
    """

    VERSION = "1.0.0"

    CHOICES = {
        "barriers": {
            "label": _("Besoins d'accompagnement"),  # Was "Freins périphériques".
            # Each element in `items` is transformed into a MultipleChoiceField.
            "items": {
                "faire_face_a_des_difficultes_administratives_ou_juridiques": {
                    "label": _(
                        "Faire face à des difficultés administratives ou juridiques"
                    ),
                    "items": [
                        {
                            "value": "connaitre_les_voies_de_recours_face_a_une_discrimination",
                            "label": _(
                                "Connaitre les voies de recours face à une discrimination"
                            ),
                        },
                        {
                            "value": "prendre_en_compte_une_problematique_judiciaire",
                            "label": _(
                                "Prendre en compte une problématique judiciaire"
                            ),
                        },
                        {
                            "value": "regler_un_probleme_administratif_ou_juridique",
                            "label": _("Régler un problème administratif ou juridique"),
                        },
                    ],
                },
                "faire_face_a_des_difficultes_financieres": {
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
                "se_deplacer": {
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
                "se_loger": {
                    "label": _("Se loger"),
                    "items": [
                        {
                            "value": "se_maintenir_dans_son_logement",
                            "label": _("Se maintenir dans son logement"),
                        },
                        {
                            "value": "se_mettre_a_labri",
                            "label": _("Se mettre à l'abri"),
                        },
                        {
                            "value": "trouver_un_logement",
                            "label": _("Trouver un logement"),
                        },
                    ],
                },
                "se_soigner": {
                    "label": _("Se soigner"),
                    "items": [
                        {
                            "value": "faire_un_bilan_de_sante",
                            "label": _("Faire un bilan de santé"),
                        },
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
                "sortir_de_lisolement": {
                    "label": _("Sortir de l'isolement"),
                    "items": [
                        {
                            "value": "acceder_aux_ressources_internet_et_telephonie_mobile",
                            "label": _(
                                "Accéder aux ressources Internet et téléphonie mobile"
                            ),
                        },
                        {
                            "value": "creer_des_liens_sociaux_rompre_avec_lisolement",
                            "label": _(
                                "Créer des liens sociaux, rompre avec l'isolement"
                            ),
                        },
                        {
                            "value": "participer_a_des_activites_sociales_et_culturelles",
                            "label": _(
                                "Participer à des activités sociales et culturelles"
                            ),
                        },
                    ],
                },
                "maitriser_les_savoirs_de_base": {
                    "label": _("Maitriser les savoirs de base"),
                    "items": [
                        {
                            "value": "sortir_dune_situation_dillettrisme_danalphabetisme",
                            "label": _(
                                "Sortir d'une situation d'illettrisme, d'analphabétisme"
                            ),
                        },
                        {
                            "value": "suivre_une_formation_francais_langue_etrangere",
                            "label": _(
                                "Suivre une formation Français Langue Étrangère"
                            ),
                        },
                        {"value": "savoir_compter", "label": _("Savoir compter")},
                    ],
                },
                "surmonter_des_contraintes_familiales": {
                    "label": _("Surmonter des contraintes familiales"),
                    "items": [
                        {
                            "value": "etre_accompagne_dans_la_perte_dun_proche",
                            "label": _("Etre accompagné dans la perte d'un proche"),
                        },
                        {
                            "value": "etre_aide_dans_la_parentalite_et_la_prevention",
                            "label": _(
                                "Etre aidé dans la parentalité et la prévention"
                            ),
                        },
                        {
                            "value": "faire_face_a_des_difficulte_educatives",
                            "label": _("Faire face à des difficulté éducatives"),
                        },
                        {
                            "value": "faire_face_a_la_prise_en_charge_dune_personne_dependante",
                            "label": _(
                                "Faire face à la prise en charge d'une personne dépendante"
                            ),
                        },
                        {
                            "value": "faire_garder_son_enfant",
                            "label": _("Faire garder son enfant"),
                        },
                        {
                            "value": "se_faire_aider_en_cas_de_conflit_familial_et_ou_separation",
                            "label": _(
                                "Se faire aider en cas de conflit familial et / ou séparation"
                            ),
                        },
                    ],
                },
            },
        },
        "administrative_criteria": {
            "label": _("Critères administratifs"),
            # Each element in `items` is transformed into a MultipleChoiceField.
            "items": {
                "criteres_administratifs_de_niveau_1": {
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
                            "label": _(
                                "Personne sans emploi de très longue durée (+24 mois)"
                            ),
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
                "criteres_administratifs_de_niveau_2": {
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
                            "help": _(
                                "Demandeur d'emploi de longue durée (inscrit à Pôle emploi)"
                            ),
                            "url": None,
                        },
                        {
                            "value": "personne_sans_emploi_de_longue_duree_12_mois",
                            "label": _(
                                "Personne sans emploi de longue durée (+12 mois)"
                            ),
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
                            "label": _(
                                "Personnes ayant fait l'objet d'un licenciement économique"
                            ),
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
                            "help": _(
                                "Quartier prioritaire de la politique de la ville"
                            ),
                            "url": "https://sig.ville.gouv.fr/",
                        },
                    ],
                },
            },
        },
    }

    ERROR_BARRIERS = _("Vous devez indiquer au moins un besoin d'accompagnement.")
    ERROR_ADMINISTRATIVE_CRITERIA = _(
        "La personne doit répondre à au moins un critère administratif de "
        "niveau 1 ou au cumul d'au moins trois critères administratifs de "
        "niveau 2."
    )
    ERROR_ADMINISTRATIVE_CRITERIA_LEVEL2 = _(
        "La personne doit répondre au cumul d'au moins trois critères "
        "administratifs de niveau 2."
    )

    def __init__(self, user_info, job_seeker, *args, **kwargs):
        self.user_info = user_info
        self.job_seeker = job_seeker
        super().__init__(*args, **kwargs)

        for category in self.CHOICES.values():
            sub_categories = category["items"]
            for k, v in sub_categories.items():
                self.fields[k] = forms.MultipleChoiceField(
                    label=v["label"],
                    widget=forms.CheckboxSelectMultiple,
                    choices=((item["value"], item["label"]) for item in v["items"]),
                    required=False,
                )

    @property
    @lru_cache(maxsize=None)
    def extra_info(self):
        """
        Return self.CHOICES as a flat dict where each key is an input value.
        It's purpose is to be used in the HTML template.
        E.g.:
            {
                'deld_12_mois': {
                    'value': 'deld_12_mois',
                    'label': 'DELD (+12 mois)',
                    'written_proof': 'Attestation Pôle emploi',
                    'help': "Demandeur d'emploi de longue durée (inscrit à Pôle emploi)",
                    'url': None
                },
                ...
            }
        """
        info = {}
        for category in self.CHOICES.values():
            sub_categories = category["items"]
            for v in sub_categories.values():
                for sub_item in v["items"]:
                    info[sub_item["value"]] = sub_item
        return info

    def clean(self):
        """
        To validate eligibility:
            - an authorized prescriber must:
                - indicate at least one peripheral barrier
            - an SIAE must:
                - indicate at least one peripheral barrier
                (and)
                - indicate the administrative criteria knowing that:
                    - the person must meet at least one level 1 criteria
                    (or)
                    - the person must meet at least three level 2 criteria
        """
        cleaned_data = super().clean()

        is_authorized_prescriber = self.user_info.is_authorized_prescriber
        is_siae = self.user_info.siae is not None

        if not any([is_authorized_prescriber, is_siae]):
            return

        checked_num = {k: len(v) for k, v in cleaned_data.items()}

        barriers_num = sum(
            [
                v
                for k, v in checked_num.items()
                if k in self.CHOICES["barriers"]["items"].keys()
            ]
        )

        if not barriers_num:
            raise forms.ValidationError(self.ERROR_BARRIERS)

        if not is_siae:
            return

        administrative_criteria_level_1_num = checked_num.get(
            "criteres_administratifs_de_niveau_1"
        )
        administrative_criteria_level_2_num = checked_num.get(
            "criteres_administratifs_de_niveau_2"
        )
        administrative_criteria_num = (
            administrative_criteria_level_1_num + administrative_criteria_level_2_num
        )

        if not administrative_criteria_num:
            raise forms.ValidationError(self.ERROR_ADMINISTRATIVE_CRITERIA)

        if (
            not administrative_criteria_level_1_num
            and administrative_criteria_level_2_num < 3
        ):
            raise forms.ValidationError(self.ERROR_ADMINISTRATIVE_CRITERIA_LEVEL2)

    def get_human_readable_data(self):
        """
        Return the checked items as a human readable structure, e.g.:
            {
                "Besoins d'accompagnement": [
                    [
                        "Faire face à des difficultés administratives ou juridiques",
                        [
                            "Connaitre les voies de recours face à une discrimination",
                            "Prendre en compte une problématique judiciaire",
                        ],
                    ]
                ],
                "Critères administratifs": [
                    [
                        "Critères administratifs de niveau 2",
                        ["Senior (+50 ans)", "Travailleur handicapé", "Primo arrivant"],
                    ]
                ],
            }
        """
        data = {}

        for key, choices in self.cleaned_data.items():

            if choices:

                field = self.fields[key]

                choices_labels = []
                for choice in choices:
                    choice_label = dict(field.choices)[choice]
                    choices_labels.append(choice_label)

                labels = [field.label, choices_labels]

                category_label = (
                    self.CHOICES["barriers"]["label"]
                    if key in self.CHOICES["barriers"]["items"]
                    else self.CHOICES["administrative_criteria"]["label"]
                )
                data.setdefault(category_label, []).append(labels)

        return data

    def save_diagnosis(self):
        """
        Save the result of the form in DB.
        """
        data = {
            "job_seeker": self.job_seeker,
            "author": self.user_info.user,
            "author_kind": self.user_info.kind,
            "author_siae": self.user_info.siae,
            "author_prescriber_organization": self.user_info.prescriber_organization,
            "form_version": self.VERSION,
            "form_cleaned_data": json.dumps(self.cleaned_data),
            "data": json.dumps(self.get_human_readable_data()),
        }
        diagnosis = EligibilityDiagnosis(**data)
        diagnosis.save()
        return diagnosis
