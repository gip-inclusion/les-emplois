import datetime
import random
import string

import factory
import factory.fuzzy
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.geiq.models import (
    Employee,
    EmployeePrequalification,
    ImplementationAssessment,
    ImplementationAssessmentCampaign,
)
from itou.users.enums import Title
from tests.companies import factories as companies_factories
from tests.utils.test import create_fake_postcode


class ImplementationAssessmentCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImplementationAssessmentCampaign

    year = factory.fuzzy.FuzzyInteger(2020, 2023)
    submission_deadline = factory.LazyAttribute(lambda obj: datetime.date(obj.year + 1, 7, 1))
    review_deadline = factory.LazyAttribute(lambda obj: datetime.date(obj.year + 1, 8, 1))


class ImplementationAssessmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImplementationAssessment

    campaign = factory.SubFactory(ImplementationAssessmentCampaignFactory)
    company = factory.SubFactory(companies_factories.CompanyFactory, kind=CompanyKind.GEIQ)
    label_id = factory.Sequence(int)
    other_data = factory.LazyFunction(dict)


class EmployeeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Employee

    assessment = factory.SubFactory(ImplementationAssessmentFactory)
    label_id = factory.Sequence(int)
    last_name = factory.Faker("last_name")
    first_name = factory.Faker("first_name")
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    title = factory.fuzzy.FuzzyChoice(Title.values)
    other_data = factory.LazyFunction(dict)
    annex1_nb = 0
    annex2_level1_nb = 0
    annex2_level2_nb = 0
    allowance_amount = 0
    support_days_nb = 0


class PrequalificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmployeePrequalification

    employee = factory.SubFactory(EmployeeFactory)
    label_id = factory.Sequence(int)
    start_at = factory.Faker("date_time_between", start_date="-5y", end_date="-6M", tzinfo=datetime.UTC)
    end_at = factory.LazyAttribute(lambda obj: obj.start_at + datetime.timedelta(days=random.randint(0, 500)))
    other_data = factory.LazyFunction(dict)


class GeiqLabelDataFactory(factory.DictFactory):
    id = factory.Sequence(int)
    siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    # All the following fields are not really important
    # 1_000_000_000 timestamp is ~ 2001-09-09
    date_creation = factory.Sequence(lambda n: (1_000_000_000 + n * 24 * 3600) * 1_000)
    nom = factory.Sequence(lambda n: f"GEIQ {n}")
    addresse = factory.Faker("street_address", locale="fr_FR")
    addresse2 = ""
    cp = factory.LazyFunction(create_fake_postcode)
    ville = factory.Faker("city", locale="fr_FR")
    telephone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    email = factory.Faker("email", locale="fr_FR")
    is_adherent_ffgeiq = True
    is_accompte_regle = None
    is_solde_regle = None
    has_mark_documents_finished = None
    has_mark_adherent_instance_finished = None
    has_mark_prerecrutement_finished = None
    has_mark_decompte_heures_finished = None
    has_mark_complement_finished = None
    has_mark_accompagnement_finished = None
    has_mark_compte_resultat_finished = None
    has_referent_handicap = False
    is_main_instructeur = True
    afficher_dans_statistique = True
    naf = {"id": 3337, "code": "78.30", "nom": "[78.30] Autre mise à disposition de ressources humaines"}
    secteurs_activite = [{"id": 109, "nom": "Aide à la personne", "code": "AAD"}]
    ccn = {
        "id": 638,
        "nom": (
            "Convention collective nationale de la branche de l'aide, de "
            "l'accompagnement, des soins et des services à domicile"
        ),
    }
    antennes = []
    opca = {}
    presidence = {}
    equipe_administratives = []
    direction = []
    autre_prestastion = ""
    event_outside_meetings = factory.Faker("paragraphs", nb=3)
    suivi_par = ""
    email_suivi_par = factory.Faker("email", locale="fr_FR")
    document_commentaires_eventuels = factory.Faker("paragraphs", nb=1)
    region = {"id": 23, "libelle": "Centre Val de Loire", "code": "I6", "remote_id": "1690"}
    accord_listing_adherents = False
    geiq_used_import = "no_history"


def _date_to_label_iso_format(date):
    return datetime.datetime.combine(date, datetime.time.min, tzinfo=timezone.get_current_timezone()).isoformat()


class SalarieLabelDataFactory(factory.DictFactory):
    class Meta:
        exclude = ("_date_creation", "_date_naissance")

    id = factory.Sequence(int)
    _date_creation = factory.fuzzy.FuzzyDate(datetime.date(2010, 1, 1), datetime.date(2024, 1, 1))
    date_creation = factory.LazyAttribute(lambda obj: _date_to_label_iso_format(obj._date_creation))
    nom = factory.Faker("last_name")
    prenom = factory.Faker("first_name")
    adresse_ligne_1 = None
    adresse_ligne_2 = None
    adresse_code_postal = None
    adresse_ville = None
    numero = None
    _date_naissance = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    date_naissance = factory.LazyAttribute(lambda obj: _date_to_label_iso_format(obj._date_naissance))
    sexe = factory.fuzzy.FuzzyChoice(["H", "F"])
    prescripteur = factory.fuzzy.FuzzyChoice(
        [
            {"id": 1, "libelle": "Pôle Emploi", "libelle_abr": "PE"},
            {"id": 2, "libelle": "Missions locales", "libelle_abr": "ML"},
            {"id": 3, "libelle": "Cap Emploi", "libelle_abr": "CAP_EMPLOI"},
            {"id": 4, "libelle": "Entreprises adhérentes", "libelle_abr": "EA"},
            {"id": 5, "libelle": "Parrainage de salariés", "libelle_abr": "PS"},
            {"id": 6, "libelle": "Organisme de formation", "libelle_abr": "OF"},
            {"id": 7, "libelle": "Annonces presse / internet", "libelle_abr": "ANNONCES_PI"},
            {"id": 8, "libelle": "Candidature spontanée", "libelle_abr": "CS"},
            {"id": 9, "libelle": "Forum", "libelle_abr": "FORUM"},
            {"id": 10, "libelle": "PLIE", "libelle_abr": "PLIE"},
            {"id": 11, "libelle": "SIAE et consors", "libelle_abr": "SIAE_CONS"},
            {"id": 12, "libelle": "Collectivité territoriale (PDI…)", "libelle_abr": "CT"},
            {"id": 13, "libelle": "Autres", "libelle_abr": "AUTRE"},
        ]
    )

    prescripteur_autre = None
    qualification = factory.fuzzy.FuzzyChoice(
        [
            {"id": 1, "libelle": "Sans qualification", "libelle_abr": "SQ"},
            {"id": 2, "libelle": "Niveau 3 (CAP, BEP)", "libelle_abr": "N3"},
            {"id": 3, "libelle": "Niveau 4 (BP, Bac Général, Techno ou Pro, BT)", "libelle_abr": "N4"},
            {"id": 4, "libelle": "Niveau 5 ou + (Bac+2 ou +)", "libelle_abr": "N5"},
        ]
    )
    is_bac_general = factory.fuzzy.FuzzyChoice([None, True, False])
    geiq_id = factory.fuzzy.FuzzyInteger(1, 1000)
    statuts_prioritaire = factory.LazyFunction(
        lambda: random.sample(
            [
                {
                    "id": 1,
                    "libelle": "Personne éloignée du marché du travail (> 1 an)",
                    "libelle_abr": "DELD",
                    "niveau": 99,
                },
                {"id": 2, "libelle": "Bénéficiaire de minima sociaux", "libelle_abr": "MINSOC", "niveau": 99},
                {
                    "id": 3,
                    "libelle": "Personne bénéficiant ou sortant d’un dispositif d’insertion (PLIE – SIAE – CUI – EA…)",
                    "libelle_abr": "SIAE/CUI",
                    "niveau": 99,
                },
                {"id": 4, "libelle": "Personne en situation de handicap", "libelle_abr": "Pers. SH", "niveau": 99},
                {
                    "id": 5,
                    "libelle": "Personne issue de quartier ou zone prioritaire (QPV – ZRR)",
                    "libelle_abr": "QPV/ZRR",
                    "niveau": 99,
                },
                {
                    "id": 6,
                    "libelle": "Personne sortant de prison ou sous main de justice",
                    "libelle_abr": "Prison",
                    "niveau": 99,
                },
                {
                    "id": 7,
                    "libelle": "Personne en reconversion professionnelle contrainte",
                    "libelle_abr": "Reconv.",
                    "niveau": 99,
                },
                {
                    "id": 8,
                    "libelle": (
                        "Jeunes de moins de 26 ans disposant au plus d’une qualification de niveau 4 sans expérience "
                        "professionnelle ou n’ayant pas exercé une activité professionnelle depuis au moins 2 ans en "
                        "rapport avec leur qualification sans emploi et ne suivant pas des études ou une formation"
                    ),
                    "libelle_abr": "-26 SQ",
                    "niveau": 99,
                },
                {"id": 9, "libelle": "Personne de plus de 45 ans", "libelle_abr": "+45", "niveau": 99},
                {"id": 10, "libelle": "Aucun", "libelle_abr": "Aucun", "niveau": 99},
                {
                    "id": 11,
                    "libelle": "Personne bénéficiant du statut de la protection internationale",
                    "libelle_abr": "Refug.",
                    "niveau": 99,
                },
                {
                    "id": 12,
                    "libelle": "Demandeur d’emploi de très longue durée (24 mois et plus)",
                    "libelle_abr": "DELD24+",
                    "niveau": 1,
                },
                {"id": 13, "libelle": "Bénéficiaire du RSA", "libelle_abr": "RSA", "niveau": 1},
                {
                    "id": 14,
                    "libelle": "Allocataire de l’allocation de solidarité spécifique (ASS)",
                    "libelle_abr": "ASS",
                    "niveau": 1,
                },
                {
                    "id": 15,
                    "libelle": "Allocataire de l’allocation adulte handicapé (AAH)",
                    "libelle_abr": "AAH",
                    "niveau": 1,
                },
                {"id": 16, "libelle": "Niveau d’étude 3 ou infra", "libelle_abr": "NE3I", "niveau": 2},
                {"id": 17, "libelle": "Senior (+50 ans)", "libelle_abr": "+50", "niveau": 2},
                {"id": 18, "libelle": "Jeunes (-26 ans)", "libelle_abr": "-26", "niveau": 2},
                {
                    "id": 19,
                    "libelle": "Sortant de l’aide sociale à l’enfance (ASE)",
                    "libelle_abr": "ASE",
                    "niveau": 2,
                },
                {
                    "id": 20,
                    "libelle": "Demandeur d’emploi de longue durée (12 à 24 mois)",
                    "libelle_abr": "DELD12/24",
                    "niveau": 2,
                },
                {"id": 21, "libelle": "Travailleur handicapé", "libelle_abr": "TH", "niveau": 2},
                {"id": 22, "libelle": "Parent isolé", "libelle_abr": "PI", "niveau": 2},
                {
                    "id": 23,
                    "libelle": "Personne sans hébergement ou hébergée ou ayant un parcours de rue",
                    "libelle_abr": "PSH/PR",
                    "niveau": 2,
                },
                {
                    "id": 24,
                    "libelle": "Réfugié statutaire, protégé subsidiaire ou demandeur d’asile",
                    "libelle_abr": "RS/PS/DA",
                    "niveau": 2,
                },
                {
                    "id": 25,
                    "libelle": "Résident Zone de Revitalisation Rurale (ZRR)",
                    "libelle_abr": "ZRR",
                    "niveau": 2,
                },
                {
                    "id": 26,
                    "libelle": "Résident Quartier prioritaire de la Politique de la Ville (QPV)",
                    "libelle_abr": "QPV",
                    "niveau": 2,
                },
                {
                    "id": 27,
                    "libelle": "Sortant de détention ou personne placée sous main de justice",
                    "libelle_abr": "Detention/MJ",
                    "niveau": 2,
                },
                {
                    "id": 28,
                    "libelle": "Non-maîtrise de la langue française",
                    "libelle_abr": "FR non maitrisé",
                    "niveau": 2,
                },
                {"id": 29, "libelle": "Problème de mobilité", "libelle_abr": "PM", "niveau": 2},
                {
                    "id": 30,
                    "libelle": "Est prescrit via la Plateforme de l’inclusion par un prescripteur habilité",
                    "libelle_abr": "Prescrit",
                    "niveau": 1,
                },
                {
                    "id": 31,
                    "libelle": "Personne en reconversion professionnelle volontaire (Expérimentation. Hors critères)",
                    "libelle_abr": "Reconv.Vol",
                    "niveau": 99,
                },
            ],
            random.randint(0, 5),
        )
    )
    precision_status_prio = None
    identifiant = factory.LazyAttribute(lambda obj: f"{obj.nom} {obj.prenom}")
    identifiant_sans_accent = factory.LazyAttribute(lambda obj: obj.identifiant.encode("ascii", "ignore").decode())
    is_imported = None


class SalarieContratLabelDataFactory(factory.DictFactory):
    class Meta:
        exclude = ("_date_debut",)

    id = factory.Sequence(int)
    salarie = factory.SubFactory(SalarieLabelDataFactory)
    antenne = {"nom": "GEIQ AVENIR CHR", "id": 0}
    _date_debut = factory.fuzzy.FuzzyDate(datetime.date(2022, 1, 1), datetime.date(2024, 1, 1))
    date_debut = factory.LazyAttribute(lambda obj: _date_to_label_iso_format(obj._date_debut))
    date_fin = factory.LazyAttribute(
        lambda obj: _date_to_label_iso_format(obj._date_debut + datetime.timedelta(days=random.randint(0, 500)))
    )
    date_fin_contrat = None
    heures_formation_prevue = factory.fuzzy.FuzzyInteger(0, 600)
    organisme_formation = ""
    metier_prepare = factory.Faker("job", locale="fr_FR")
    formation_complementaire_prevue = ""
    is_multi_mad = False
    mad_nb_entreprises = None
    tarif_mad = 15
    is_remuneration_superieur_minima = False
    is_temps_plein = True
    state = 3
    rupture = factory.fuzzy.FuzzyChoice([None, True, False])
    is_present_in_examen = False
    is_qualification_obtenue = None
    metier_correspondant = None
    formation_complementaire = None
    heures_formation_realisee = None
    qualification_visee = factory.fuzzy.FuzzyChoice(
        [
            [],  # Yes. That's an empty list. I don't make the rules.
            {"id": 1, "libelle": "Non concerné", "libelle_abr": "NC"},
            {"id": 2, "libelle": "Niveau 3 (CAP, BEP)", "libelle_abr": "N3"},
            {"id": 3, "libelle": "Niveau 4 (BP, Bac Général, Techno ou Pro, BT)", "libelle_abr": "N4"},
            {"id": 4, "libelle": "Niveau 5 ou + (Bac+2 ou +)", "libelle_abr": "N5"},
        ]
    )
    type_qualification_visee = factory.fuzzy.FuzzyChoice(
        [
            None,
            {"id": 1, "libelle": "Diplôme d’État ou Titre homologué", "libelle_abr": "RNCP"},
            {"id": 2, "libelle": "CQP", "libelle_abr": "CQP"},
            {"id": 3, "libelle": "Positionnement de CCN", "libelle_abr": "CCN"},
            {"id": 4, "libelle": "Bloc(s) de compétences enregistrées au RNCP", "libelle_abr": "BLOC"},
        ]
    )
    type_qualification_obtenu = None
    qualification_obtenu = []
    nature_contrat = factory.fuzzy.FuzzyChoice(
        [
            {
                "id": 1,
                "libelle": "Contrat de professionnalisation",
                "libelle_abr": "CPRO",
                "groupe": "1",
                "precision": False,
                "formation": True,
            },
            {
                "id": 2,
                "libelle": "Contrat d’apprentissage",
                "libelle_abr": "CAPP",
                "groupe": "1",
                "precision": False,
                "formation": True,
            },
            {
                "id": 3,
                "libelle": "CUI (toute catégorie)",
                "libelle_abr": "CUI+F",
                "groupe": "1",
                "precision": True,
                "formation": True,
            },
            {
                "id": 4,
                "libelle": "CUI (toute catégorie)",
                "libelle_abr": "CUI",
                "groupe": "2",
                "precision": True,
                "formation": False,
            },
            {"id": 5, "libelle": "CDD", "libelle_abr": "CDD", "groupe": "2", "precision": False, "formation": False},
            {"id": 6, "libelle": "CDI", "libelle_abr": "CDI", "groupe": "2", "precision": False, "formation": False},
            {
                "id": 7,
                "libelle": "Autre",
                "libelle_abr": "Autre F",
                "groupe": "1",
                "precision": False,
                "formation": True,
            },
            {
                "id": 9,
                "libelle": "CDD - CPF",
                "libelle_abr": "CDD+CPF",
                "groupe": "1",
                "precision": False,
                "formation": True,
            },
            {
                "id": 10,
                "libelle": "CDD - Autre",
                "libelle_abr": "CDD+autre",
                "groupe": "1",
                "precision": False,
                "formation": True,
            },
            {
                "id": 11,
                "libelle": "Autre",
                "libelle_abr": "Autre SF",
                "groupe": "1",
                "precision": False,
                "formation": False,
            },
        ]
    )
    nature_contrat_precision = factory.fuzzy.FuzzyChoice(
        [[], {"id": 1, "libelle": "CIE", "libelle_abr": "CIE"}, {"id": 2, "libelle": "CAE", "libelle_abr": "CAE"}]
    )
    nature_contrat_autre_precision = ""
    secteur_activite = factory.fuzzy.FuzzyChoice(
        [
            {"id": 1, "nom": "Accueil et Relation Client", "code": "ARC"},
            {"id": 2, "nom": "Agricole et Espaces Verts", "code": "AEV"},
            {"id": 3, "nom": "Agroalimentaire et Logistique", "code": "AEL"},
            {"id": 4, "nom": "Aide à Domicile", "code": "AD"},
            {"id": 5, "nom": "BTP et Travaux Publics", "code": "BTP"},
            {"id": 6, "nom": "Industrie", "code": "INDUS"},
            {"id": 7, "nom": "Médico-social", "code": "MS"},
            {"id": 8, "nom": "Propreté", "code": "PRO"},
            {"id": 9, "nom": "Transport", "code": "TRA"},
            {"id": 10, "nom": "Autre", "code": "AUTRE"},
            {"id": 11, "nom": "Non-concerné", "code": "NC"},
        ]
    )
    mode_validation = None
    emploi_sorti = factory.fuzzy.FuzzyChoice(
        [
            None,
            {"id": 1, "libelle": "Dans une entreprise adhérente", "libelle_abr": "ADH"},
            {"id": 2, "libelle": "Dans une entreprise non adhérente", "libelle_abr": "NADH"},
            {"id": 3, "libelle": "Maintien dans le Geiq", "libelle_abr": "GEIQ"},
            {"id": 4, "libelle": "Création ou reprise d’entreprise", "libelle_abr": "ENT"},
            {"id": 5, "libelle": "Chômage", "libelle_abr": "CHOM"},
            {"id": 6, "libelle": "Retour en formation (hors alternance)", "libelle_abr": "FORM"},
            {"id": 8, "libelle": "Maladie / Invalidité / Maternité / Incarcération", "libelle_abr": "MIMI"},
            {"id": 9, "libelle": "Ne sait pas", "libelle_abr": "NSP"},
            {"id": 10, "libelle": "Autre", "libelle_abr": "AUTR"},
            {"id": 11, "libelle": "Groupement d'employeurs", "libelle_abr": "EMP"},
        ]
    )
    emploi_sorti_precision = None
    mise_en_situation_professionnelle_bool = factory.LazyAttribute(
        lambda obj: bool(obj.mise_en_situation_professionnelle)
    )
    mise_en_situation_professionnelle_precision = ""
    mise_en_situation_professionnelle = factory.fuzzy.FuzzyChoice(
        [
            False,
            {"id": 1, "libelle": "PMSMP", "libelle_abr": "PMSMP"},
            {"id": 2, "libelle": "MRS", "libelle_abr": "MRS"},
            {"id": 3, "libelle": "STAGE", "libelle_abr": "STAGE"},
            {"id": 5, "libelle": "AUTRE", "libelle_abr": "AUTRE"},
        ]
    )
    emploi_sorti_precision_text = None
    signer_cadre_clause_insertion = False
    is_contrat_pro_experimental = False
    is_contrat_pro_associe_vae_inversee = False
    nb_heure_hebdo = None
    libre_cc_vise = ""
    contrat_opco = ""
    accompagnement_avant_contrat = None
    accompagnement_apres_contrat = None
    hors_alternance_precision = ""
    modalite_formation = []
    heures_accompagnement_vae_prevue = None
    heures_suivi_evaluation_competences_geiq_prevues = None
    code_rncp = None
    type_validation = []
    is_refus_cdd_cdi = False


class SalariePreQualificationLabelDataFactory(factory.DictFactory):
    class Meta:
        exclude = ("_date_debut",)

    id = factory.Sequence(int)
    salarie = factory.SubFactory(SalarieLabelDataFactory)
    _date_debut = factory.fuzzy.FuzzyDate(datetime.date(2022, 1, 1), datetime.date(2024, 1, 1))
    date_debut = factory.LazyAttribute(lambda obj: _date_to_label_iso_format(obj._date_debut))
    date_fin = factory.LazyAttribute(
        lambda obj: _date_to_label_iso_format(obj._date_debut + datetime.timedelta(days=random.randint(0, 500)))
    )
    nombre_heure_formation = factory.fuzzy.FuzzyInteger(0, 600)
    action_pre_qualification = factory.fuzzy.FuzzyChoice(
        [
            {"id": 1, "libelle": "AFPR", "libelle_abr": "AFPR"},
            {"id": 2, "libelle": "Dispositif de préqualif régional ou sectoriel", "libelle_abr": "DISPOSITIF"},
            {"id": 3, "libelle": "POE", "libelle_abr": "POE"},
            {"id": 5, "libelle": "AUTRE", "libelle_abr": "AUTRE"},
        ]
    )
    information_complementaire_contrat = None
    autre_type_prequalification_action = None
