import enum

from itou.utils.apis.pole_emploi import Endpoints


API_RECHERCHE_RESPONSE_KNOWN = {
    "idNationalDE": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
    "codeSortie": "S001",
    "certifDE": False,
}

API_RECHERCHE_RESPONSE_MANY_RESULTS = {
    "idNationalDE": "",
    "codeSortie": "S002",
    "certifDE": False,
}

API_RECHERCHE_RESPONSE_ERROR = {
    "idNationalDE": "",
    "codeSortie": "R010",
    "certifDE": False,
}

API_MAJPASS_RESPONSE_OK = {
    "codeSortie": "S000",
    "idNational": "some_id_national",
    "message": "Pass IAE prescrit",
}

API_MAJPASS_RESPONSE_ERROR = {
    "codeSortie": "S022",
    "idNational": "some_id_national",
    "message": "SD non installé : : Refus du PASS IAE",
}

API_REFERENTIEL_NATURE_CONTRATS_RESPONSE_OK = [
    {"code": "E1", "libelle": "Contrat travail"},
    {"code": "E2", "libelle": "Contrat apprentissage"},
    {"code": "FA", "libelle": "Act. Formation pré.recrut."},
    {"code": "FJ", "libelle": "Contrat pacte"},
    {"code": "FS", "libelle": "Cont. professionnalisation"},
    {"code": "FT", "libelle": "CUI - CAE"},
    {"code": "FU", "libelle": "CUI - CIE"},
    {"code": "I1", "libelle": "Insertion par l'activ.éco."},
    {"code": "NS", "libelle": "Emploi non salarié"},
    {"code": "FV", "libelle": "Prépa.opérationnel.emploi"},
    {"code": "FW", "libelle": "Emploi Avenir non marchand"},
    {"code": "FX", "libelle": "Emploi Avenir marchand"},
    {"code": "FY", "libelle": "Emploi Avenir Professeur"},
    {"code": "PS", "libelle": "Portage salarial"},
    {"code": "PR", "libelle": "Contrat PrAB"},
    {"code": "CC", "libelle": "CDI de chantier ou d’opération"},
    {"code": "CU", "libelle": "Contrat d'usage"},
    {"code": "EE", "libelle": "Contrat d'Engagement Educatif"},
    {"code": "ER", "libelle": "Engagement à servir dans la réserve"},
    {"code": "CI", "libelle": "Contrat intermittent"},
]

API_OFFRES_RESPONSE_OK = [
    {
        "id": "FOOBAR",
        "intitule": "Mécanicien de maintenance (F/H).",
        "description": "Sous la responsabilité, vous avez une mission",
        "dateCreation": "2022-11-23T18:11:41.000Z",
        "dateActualisation": "2022-11-23T18:11:42.000Z",
        "lieuTravail": {
            "libelle": "45 - ST CLAUDE",
            "latitude": 46.40031,
            "longitude": 5.860239,
            "codePostal": "39200",
            "commune": "39478",
        },
        "romeCode": "I1304",
        "romeLibelle": "Installation et maintenance d'équipements industriels et d'exploitation",
        "appellationlibelle": "Technicien / Technicienne de maintenance industrielle",
        "entreprise": {
            "nom": "RANDSTAD",
            "description": "Randstad vous ouvre toutes les portes de l'emploi",
            "logo": "https://entreprise.pole-emploi.fr/static/img/logos/Vxxxxxxxxxxxxxxxxx.png",
            "entrepriseAdaptee": False,
        },
        "typeContrat": "CDI",
        "typeContratLibelle": "Contrat à durée indéterminée",
        "natureContrat": "Contrat travail",
        "experienceExige": "S",
        "experienceLibelle": "3 mois",
        "formations": [
            {
                "codeFormation": "23684",
                "domaineLibelle": "entretien mécanique",
                "niveauLibelle": "Bac ou équivalent",
                "exigence": "S",
            }
        ],
        "competences": [
            {
                "code": "106714",
                "libelle": "Réaliser les réglages",
                "exigence": "S",
            },
            {"code": "123301", "libelle": "Réparer une pièce défectueuse", "exigence": "S"},
        ],
        "salaire": {"libelle": "Annuel de 26400,00 Euros sur 12 mois"},
        "dureeTravailLibelle": "35H Horaires normaux",
        "dureeTravailLibelleConverti": "Temps plein",
        "alternance": False,
        "contact": {
            "nom": "RANDSTAD - Mme Lea BLONDEAU",
            "coordonnees1": "https://www.randstad.fr/offre/001-SM-DEADBEEF_01R/A",
            "commentaire": "Candidater sur le site du recruteur",
            "urlPostulation": "https://www.randstad.fr/offre/001-SM-DEADBEEF_01R/A",
        },
        "nombrePostes": 1,
        "accessibleTH": False,
        "qualificationCode": "7",
        "qualificationLibelle": "Technicien",
        "secteurActivite": "78",
        "secteurActiviteLibelle": "Activités des agences de travail temporaire",
        "origineOffre": {
            "origine": "1",
            "urlOrigine": "https://candidat.pole-emploi.fr/offres/recherche/detail/FOOBAR",
        },
        "offresManqueCandidats": False,
        "entrepriseAdaptee": False,
        "employeurHandiEngage": False,
    },
    {
        "id": "OHNOES",
        "intitule": "Assistant (F/H)",
        "description": "Rattaché au responsable",
        "dateCreation": "2022-11-23T18:11:36.000Z",
        "dateActualisation": "2022-11-23T18:11:37.000Z",
        "lieuTravail": {
            "libelle": "55 - ST GERMAIN EN COGLES",
            "latitude": 48.400383,
            "longitude": -1.255488,
            "codePostal": "35133",
            "commune": "35273",
        },
        "romeCode": "M1607",
        "romeLibelle": "Secrétariat",
        "appellationlibelle": "Secrétaire",
        "entreprise": {
            "nom": "RANDSTAD",
            "description": "Randstad vous ouvre toutes les portes de l'emploi",
            "logo": "https://entreprise.pole-emploi.fr/static/img/logos/gloubiboulga.png",
            "entrepriseAdaptee": False,
        },
        "typeContrat": "CDI",
        "typeContratLibelle": "Contrat",
        "natureContrat": "Contrat travail",
        "experienceExige": "D",
        "experienceLibelle": "Débutant OK",
        "formations": [
            {
                "codeFormation": "35054",
                "domaineLibelle": "secrétariat assistanat",
                "niveauLibelle": "Bac ou équivalent",
                "exigence": "S",
            }
        ],
        "competences": [
            {"code": "120722", "libelle": "Planifier des rendez-vous", "exigence": "S"},
            {"code": "121288", "libelle": "Orienter les personnes selon leur demande", "exigence": "S"},
            {"code": "124156", "libelle": "Saisir des documents num\u00e9riques", "exigence": "S"},
        ],
        "salaire": {"libelle": "Mensuel de 1710,00 Euros sur 12 mois"},
        "dureeTravailLibelle": "35H Horaires normaux",
        "dureeTravailLibelleConverti": "Temps plein",
        "alternance": False,
        "contact": {
            "nom": "RANDSTAD - Mme Emilie LECHEVALLIER",
            "coordonnees1": "https://www.randstad.fr/offre/001-ZX-BLAH",
            "commentaire": "Candidater sur le site du recruteur",
            "urlPostulation": "https://www.randstad.fr/offre/001-ZX-BLAH",
        },
        "nombrePostes": 1,
        "accessibleTH": False,
        "qualificationCode": "3",
        "qualificationLibelle": "Ouvrier qualifié (P1,P2)",
        "secteurActivite": "78",
        "secteurActiviteLibelle": "Activités des agences de travail temporaire",
        "origineOffre": {
            "origine": "1",
            "urlOrigine": "https://candidat.pole-emploi.fr/offres/recherche/detail/OHNOES",
        },
        "offresManqueCandidats": False,
        "entrepriseAdaptee": False,
        "employeurHandiEngage": False,
    },
]

API_APPELLATIONS_RESPONSE_OK = [
    {"code": "11405", "libelle": "Audioprothésiste", "metier": {"code": "J1401"}},
    {"code": "11406", "libelle": "Audiotypiste", "metier": {"code": "M1606"}},
    {"code": "11407", "libelle": "Auditeur / Auditrice comptable", "metier": {"code": "M1202"}},
    {
        "code": "11408",
        "libelle": "Auditeur comptable et financier / Auditrice comptable et financière",
        "metier": {"code": "M1202"},
    },
    {"code": "11409", "libelle": "Auditeur / Auditrice de gestion d'entreprise", "metier": {"code": "M1204"}},
    {"code": "11410", "libelle": "Auditeur / Auditrice en organisation", "metier": {"code": "M1402"}},
    {"code": "11411", "libelle": "Auditeur / Auditrice en système d'information", "metier": {"code": "M1802"}},
    {"code": "11412", "libelle": "Auditeur informaticien / Auditrice informaticienne", "metier": {"code": "M1802"}},
    {"code": "11413", "libelle": "Auditeur / Auditrice interne", "metier": {"code": "M1202"}},
    {"code": "11415", "libelle": "Auditeur / Auditrice qualité en industrie", "metier": {"code": "H1502"}},
    {"code": "11416", "libelle": "Auditeur social / Auditrice sociale", "metier": {"code": "M1402"}},
    {"code": "11425", "libelle": "Auteur / Auteure carnettiste", "metier": {"code": "E1102"}},
    {"code": "11426", "libelle": "Auteur / Auteure de bande dessinée", "metier": {"code": "E1102"}},
    {"code": "11427", "libelle": "Auteur / Auteure dramatique", "metier": {"code": "E1102"}},
]


class ResponseKind(enum.Enum):
    CERTIFIED = "certified"  # 200
    CERTIFIED_FOR_EVER = "certified_for_ever"  # 200
    NOT_CERTIFIED = "not_certified"  # 200
    NOT_FOUND = "not_found"  # 200
    MULTIPLE_USERS_RETURNED = "multiple_users_returned"  # 200
    BAD_REQUEST = "validation_error"  # 400
    FORBIDDEN = "not_allowed"  # 403
    INTERNAL_SERVER_ERROR = "server_error"  # 500
    SERVICE_UNAVAILABLE = "service_unavailable"  # 503


RESPONSES = {
    Endpoints.RECHERCHER_USAGER_DATE_NAISSANCE_NIR: {
        ResponseKind.CERTIFIED: {
            "codeRetour": "S001",
            "message": "Approchant trouvé",
            "jetonUsager": "a_long_token",
            "topIdentiteCertifiee": "O",
        },
        ResponseKind.NOT_CERTIFIED: {
            "codeRetour": "S001",
            "message": "Approchant trouvé",
            "jetonUsager": "a_long_token",
            "topIdentiteCertifiee": "N",
        },
        ResponseKind.NOT_FOUND: {
            "codeRetour": "S002",
            "message": "Aucun approchant trouvé",
            "jetonUsager": None,
            "topIdentiteCertifiee": None,
        },
        ResponseKind.MULTIPLE_USERS_RETURNED: {
            "codeRetour": "S003",
            "message": "Plusieurs usagers trouvés",
            "jetonUsager": None,
            "topIdentiteCertifiee": None,
        },
        # TODO(cms): check if this is common to all endpoints and, if so, add them too.
        ResponseKind.BAD_REQUEST: {
            "codeRetour": "R997",
            "message": "Une erreur de validation s'est produite",
            "topIdentiteCertifiee": "null",
            "jetonUsager": "null",
        },
        ResponseKind.FORBIDDEN: {
            "codeRetour": "R001",
            "message": "Accès non autorisé",
            "topIdentiteCertifiee": "null",
            "jetonUsager": "null",
        },
        ResponseKind.INTERNAL_SERVER_ERROR: {
            "codeRetour": "R998",
            "message": "Un service a répondu en erreur",
            "topIdentiteCertifiee": "null",
            "jetonUsager": "null",
        },
        ResponseKind.SERVICE_UNAVAILABLE: {
            "codeRetour": "R999",
            "message": "Service indisponible, veuillez réessayer ultérieurement",
            "topIdentiteCertifiee": "null",
            "jetonUsager": "null",
        },
    },
    Endpoints.RECHERCHER_USAGER_NUMERO_FRANCE_TRAVAIL: {
        ResponseKind.CERTIFIED: {
            "codeRetour": "S001",
            "message": "Approchant trouvé",
            "jetonUsager": "a_long_token",
            "topIdentiteCertifiee": "O",
        },
    },
    Endpoints.RQTH: {
        ResponseKind.CERTIFIED: {
            "dateDebutRqth": "2024-01-20",
            "dateFinRqth": "2030-01-20",
            "source": "FRANCE TRAVAIL",
            "topValiditeRQTH": True,
        },
        ResponseKind.NOT_CERTIFIED: {
            "dateDebutRqth": "",
            "dateFinRqth": "",
            "source": "",
            "topValiditeRQTH": False,
        },
        ResponseKind.CERTIFIED_FOR_EVER: {
            "dateDebutRqth": "2024-01-20",
            "dateFinRqth": "9999-12-31",
            "source": "FRANCE TRAVAIL",
            "topValiditeRQTH": True,
        },
    },
    Endpoints.INFORMATIONS_ADMINISTRATIVES_USAGER: {
        ResponseKind.CERTIFIED: {
            "numeroFranceTravail": "12345678900",
            "adresses": [
                {
                    "codeInseeCommune": "69389",
                    "codePostal": "69009",
                    "complementAdresse": "Résidence Les Tilleuls",
                    "complementDestinataire": "Escalier C",
                    "complementDistribution": "BP 14",
                    "libelleCommune": "LYON",
                    "libellePays": "FRANCE",
                    "numeroTypeLibelleVoie": "93 Rue Marietton",
                    "indicateurResidentQPV": "NQ",
                }
            ],
            "emails": [{"adresseEmail": "john.doe@francetravail.fr"}],
            "etatCivil": {
                "civilite": "M.",
                "dateNaissance": "1998-07-11",
                "nir": "1041174010081",
                "nom": "DOE",
                "nomCorrespondance": "DOE",
                "prenom": "JOHN",
                "prenomCorrespondance": "JOHN",
            },
            "telephones": [{"numeroTelephone": "0972723949"}],
        },
    },
    Endpoints.STATUT_USAGER: {
        ResponseKind.CERTIFIED: {
            "m_contrat": {
                "m_statut": "Inscrit",
                "m_date_effet_statut": "2025-06-28",
                "m_duree_inscription_12": 9,
                "m_duree_inscription_24": 16,
                "m_duree_inscription_36": 28,
                "m_motif_inscription_code": "11",
                "m_motif_inscription_lib": "LICENCIEMENT ECONOMIQUE",
                "m_categ_inscription_code": "1",
                "m_categ_inscription_lib": "PERSONNE SANS EMPLOI DISPONIBLE DUREE INDETERMINEE PLEIN TPS",
                "m_situation_reg_emp_code": "ADR",
                "m_situation_reg_emp_lib": "AIDE DIFFERENTIELLE AU RECLASSEMENT",
                "m_motif_cloture_code": "MV",
                "m_motif_cloture_lib": "ABANDON ACTION AIDE A LA RECHERCHE D'UNE ACTIVITE SUPPRESSION DE 1 MOIS",
            },
        },
    },
    Endpoints.LECTURE_ORIENTATION_USAGER: {
        ResponseKind.CERTIFIED: [
            {
                "parcours": "PED",
                "organisme": "CD",
                "structure": {
                    "code_aurore": "NAQ0057",
                    "code_safir": "69000",
                    "libelle_structure": "Agence Mériadek",
                },
                "structure_decision": {
                    "code_aurore": "NAQ0057",
                    "code_safir": "69000",
                    "libelle_structure": "Agence Mériadek",
                },
                "statut": "DECIDE",
                "etat": "OUVERT",
                "...": "...",
                "agent_creation": "IIII9999",
                "agent_derniere_modification": "IIII9999",
                "date_entree_parcours": "2024-08-01",
                "date_sortie_parcours": "2026-02-21",
                "motif_sortie_parcours": "Exemple de motif",
                "date_creation": "2024-10-28",
                "date_modification": "2026-06-11",
                "criteres_orientation": {
                    "origine": "INSCRIPTION_CONSEILLER_CD",
                    "situation_professionnelle": "EN_ACTIVITE",
                    "type_emploi": "SAISONNIER",
                    "niveau_etude": "AFS",
                    "capacite_a_travailler": True,
                    "projet_pro": "SALARIAT",
                    "contrainte_sante": "INCAPACITE_RECHERCHE_ACTIVITE_PRO",
                    "contrainte_logement": "SANS_LOGEMENT",
                    "contrainte_mobilite": "AUCUN_MOYEN_DE_TRANSPORT",
                    "contrainte_familiale": "AIDANT_FAMILIAL",
                    "contrainte_financiere": "IMPACT_FORT_RECHERCHE_EMPLOI",
                    "contrainte_numerique": "NON_ACCES_INTERNET",
                    "contrainte_administrative_juridique": "IMPACT_FORT_RECHERCHE_EMPLOI",
                    "contrainte_francais_calcul": "IMPACT_FORT_RECHERCHE_EMPLOI",
                    "brsa": True,
                    "boe": True,
                    "baeeh": True,
                    "scolarite_etablissement_specialise": True,
                    "esat": True,
                    "boe_souhait_accompagnement": True,
                    "msa_autonomie_recherche_emploi": 1,
                    "msa_demarches_professionnelles": "AUCUNE_DEMARCHE",
                    "adresse": {
                        "code_commune": "33063",
                        "libelle_commune": "Bordeaux",
                        "code_postal": "33000",
                        "numero_type_libelle_voie": "25 rue lacroix",
                    },
                    "date_saise_données": "2025-10-02",
                },
                "decision": {
                    "etat_decision": "REFUSEE",
                    "date_decision": "2024-08-01",
                    "agent_decision": "IIII9999",
                    "motif_refus": "DECLARATION_INEXACTE",
                    "commentaire_refus": "Champ libre",
                },
            }
        ]
    },
    Endpoints.DIAGNOSTIC_USAGER_DIAGNOSTIC_AGREGE: {
        ResponseKind.CERTIFIED: {
            "besoinsParDiagnostic": [
                {
                    "diagnostic": {
                        "idDiagnostic": "uuid123",
                        "idMetierChiffre": (
                            "fab31b61-9b96-4112-afac-5020a79a21de#UzFBZk-_jtQJyyfOo2dOcgheK27ExNYoGXwpuBB_as0"
                        ),
                        "nomMetier": "Boulanger",
                        "typologie": "mÃ©tier recherchÃ©",
                        "codeTypologie": "MR",
                        "codeSousTypologie": "MR",
                        "codeRome": "F1204",
                        "codeAppellation": "19070",
                        "statut": "EN_COURS",
                        "estPrioritaire": False,
                        "agent": {
                            "id": "ertc8250",
                            "nom": "Dupont",
                            "prenom": "Fernande",
                            "structure": "CDG Alpes Haute Provence",
                        },
                        "dateMiseAJour": "2022-12-09T01:00:00.000+02:00",
                        "dateMiseAJourProjet": None,
                        "estCreationPartenaire": True,
                    },
                    "dateDerniereExplorationBesoin": "2019-05-17T16:47:11.000+02:00",
                    "agentDerniereExplorationBesoin": {
                        "id": "ertc8250",
                        "nom": "Dupont",
                        "prenom": "Fernande",
                        "structure": "CDG Alpes Haute Provence",
                    },
                    "thematiquesBesoins": [
                        {
                            "code": "1",
                            "libelle": "Choisir un métier",
                            "besoins": [
                                {
                                    "code": "1",
                                    "libelle": "Identifier ses points forts et ses compétences",
                                    "valeur": "NON_EXPLORE",
                                    "agent": None,
                                    "dateExploration": None,
                                },
                                {
                                    "code": "2",
                                    "libelle": "Connaître les opportunités d’emploi",
                                    "valeur": "NON_EXPLORE",
                                    "agent": None,
                                    "dateExploration": None,
                                },
                                {
                                    "code": "3",
                                    "libelle": "Découvrir un métier ou un secteur d’activité",
                                    "valeur": "BESOIN",
                                    "agent": {
                                        "id": "ertc8250",
                                        "nom": "Dupont",
                                        "prenom": "Fernande",
                                        "structure": "CDG Alpes Haute Provence",
                                    },
                                    "dateExploration": "2019-05-17T16:47:11.000+02:00",
                                },
                                {
                                    "code": "4",
                                    "libelle": "Confirmer son choix de métier",
                                    "valeur": "POINT_FORT",
                                    "agent": {
                                        "id": "ertc8250",
                                        "nom": "Dupont",
                                        "prenom": "Fernande",
                                        "structure": "CDG Alpes Haute Provence",
                                    },
                                    "dateExploration": "2019-05-17T16:47:11.000+02:00",
                                },
                            ],
                        },
                        {
                            "code": "2",
                            "libelle": "Se former",
                            "besoins": [
                                {
                                    "code": "5",
                                    "libelle": "Trouver sa formation",
                                    "valeur": "NON_EXPLORE",
                                    "agent": None,
                                    "dateExploration": None,
                                },
                                {
                                    "code": "6",
                                    "libelle": "Monter son dossier de formation",
                                    "valeur": "NON_EXPLORE",
                                    "agent": None,
                                    "dateExploration": None,
                                },
                            ],
                        },
                    ],
                }
            ],
            "thematiqueContrainte": {
                "agent": {
                    "id": "ertc8250",
                    "nom": "Dupont",
                    "prenom": "Fernande",
                    "structure": "CDG Alpes Haute Provence",
                },
                "dateExploration": "2021-05-17T16:47:11.000+02:00",
                "code": "7",
                "libelle": "Résoudre ses contraintes personnelles",
                "declareSansContrainte": {"flag": False, "date": "2021-05-17T16:47:11.000+02:00"},
                "contraintes": [
                    {
                        "code": "23",
                        "libelle": "Développer sa mobilité",
                        "valeur": "OUI",
                        "estPrioritaire": True,
                        "dateExploration": "2021-05-17T16:47:11.000+02:00",
                        "impact": "FAIBLE",
                        "situations": [
                            {
                                "code": "6",
                                "libelle": "Aucun moyen de transport à disposition",
                                "valeur": "NON_ABORDEE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "7",
                                "libelle": "Dépendant des transports en communs",
                                "valeur": "OUI",
                                "dateExploration": "2021-05-17T16:47:11.000+02:00",
                                "agent": {
                                    "id": "ertc8250",
                                    "nom": "Dupont",
                                    "prenom": "Fernande",
                                    "structure": "CDG Alpes Haute Provence",
                                },
                            },
                            {
                                "code": "8",
                                "libelle": "Permis non valide / suspension de permis",
                                "valeur": "NON_ABORDEE",
                                "dateExploration": None,
                                "agent": None,
                            },
                        ],
                        "objectifs": [
                            {
                                "code": "4",
                                "libelle": "Faire un point complet sur sa mobilité",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "29",
                                "libelle": "Accéder à un véhicule",
                                "valeur": "EN_COURS",
                                "dateExploration": "2021-05-17T16:47:11.000+02:00",
                                "agent": {
                                    "id": "ertc8250",
                                    "nom": "Dupont",
                                    "prenom": "Fernande",
                                    "structure": "CDG Alpes Haute Provence",
                                },
                            },
                            {
                                "code": "5",
                                "libelle": "Entretenir ou réparer son véhicule",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "6",
                                "libelle": "Obtenir le permis de conduire (code / conduite)",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "7",
                                "libelle": (
                                    "Trouver une solution de transport (hors acquisition ou entretien de véhicule)"
                                ),
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "30",
                                "libelle": "Travailler la mobilité psychologique",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                        ],
                    },
                    {
                        "code": "24",
                        "libelle": "Surmonter ses contraintes familiales",
                        "valeur": "NON_ABORDEE",
                        "estPrioritaire": False,
                        "dateExploration": None,
                        "situations": [
                            {
                                "code": "9",
                                "libelle": "Enfant(s) en situation de handicap",
                                "valeur": "NON_ABORDEE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "10",
                                "libelle": "Contrainte horaires",
                                "valeur": "NON_ABORDEE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "11",
                                "libelle": "Aidant familial (s'occuper d'un proche)",
                                "valeur": "NON_ABORDEE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "12",
                                "libelle": "Autres contraintes familiales Ã  prendre en compte",
                                "valeur": "NON_ABORDEE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "13",
                                "libelle": "Enfant(s) de moins de 3 ans sans solution de garde",
                                "valeur": "NON_ABORDEE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "14",
                                "libelle": "Attend un enfant ou plus",
                                "valeur": "NON_ABORDEE",
                                "dateExploration": None,
                                "agent": None,
                            },
                        ],
                        "objectifs": [
                            {
                                "code": "8",
                                "libelle": "Faire face à la prise en charge d'une personne dépendante",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "9",
                                "libelle": "Trouver des solutions de garde d'enfant",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "10",
                                "libelle": "Surmonter des difficultés éducatives ou de parentalité",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "11",
                                "libelle": "Faire face à un conflit familial et/ou une séparation",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "31",
                                "libelle": "Obtenir le statut d'aidant familial",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                            {
                                "code": "32",
                                "libelle": "Rompre l'isolement",
                                "valeur": "NON_ABORDE",
                                "dateExploration": None,
                                "agent": None,
                            },
                        ],
                    },
                ],
            },
            "pouvoirAgir": {
                "confiance": "NON",
                "accompagnement": "NE_SAIT_PAS",
                "resultatAnalyse": "Possible perte de confiance",
                "agent": {
                    "id": "ertc8250",
                    "nom": "Dupont",
                    "prenom": "Fernande",
                    "structure": "CDG Alpes Haute Provence",
                },
                "dateExploration": "2021-05-17T16:47:11.000+02:00",
            },
            "autonomieNumerique": {
                "dateExploration": "2021-05-17T16:47:11.000+02:00",
                "agent": {
                    "id": "ertc8250",
                    "nom": "Dupont",
                    "prenom": "Fernande",
                    "structure": "CDG Alpes Haute Provence",
                },
                "contrainte": {
                    "code": "22",
                    "libelle": "Accéder au numérique et en maîtriser les fondamentaux",
                    "valeur": "OUI",
                    "estPrioritaire": True,
                    "dateExploration": "2021-05-17T16:47:11.000+02:00",
                    "impact": "FAIBLE",
                    "situations": [
                        {
                            "code": "42",
                            "libelle": "Absence d'équipement",
                            "valeur": "OUI",
                            "dateExploration": "2021-05-17T16:47:11.000+02:00",
                            "agent": {
                                "id": "ertc8250",
                                "nom": "Dupont",
                                "prenom": "Fernande",
                                "structure": "CDG Alpes Haute Provence",
                            },
                        },
                        {
                            "code": "43",
                            "libelle": "Dispose d'un ordinateur",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "44",
                            "libelle": "Dispose d'un smartphone",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "45",
                            "libelle": "Dispose d'une tablette",
                            "valeur": "NON",
                            "dateExploration": "2021-05-17T16:47:11.000+02:00",
                            "agent": {
                                "id": "ertc8250",
                                "nom": "Dupont",
                                "prenom": "Fernande",
                                "structure": "CDG Alpes Haute Provence",
                            },
                        },
                        {
                            "code": "46",
                            "libelle": "Absence de maîtrise de l'équipement",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "47",
                            "libelle": "Absence de connexion (zone blanche)",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "48",
                            "libelle": "Absence de connexion (refus)",
                            "valeur": "OUI",
                            "dateExploration": "2021-05-17T16:47:11.000+02:00",
                            "agent": {
                                "id": "ertc8250",
                                "nom": "Dupont",
                                "prenom": "Fernande",
                                "structure": "CDG Alpes Haute Provence",
                            },
                        },
                        {
                            "code": "49",
                            "libelle": "Absence de connexion (autre)",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "50",
                            "libelle": "Absence d'adresse ou d'utilisation de la messagerie",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "51",
                            "libelle": "Absence de mobilité pour accéder à un espace numérique",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "52",
                            "libelle": "Difficulté à réaliser des démarches administratives en ligne",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "53",
                            "libelle": "En difficulté sur le numérique (résultat Pix emploi <50%)",
                            "valeur": "NON_ABORDEE",
                            "dateExploration": None,
                            "agent": None,
                        },
                    ],
                    "objectifs": [
                        {
                            "code": "1",
                            "libelle": "Acquérir un équipement",
                            "valeur": "EN_COURS",
                            "dateExploration": "2021-05-17T16:47:11.000+02:00",
                            "agent": {
                                "id": "ertc8250",
                                "nom": "Dupont",
                                "prenom": "Fernande",
                                "structure": "CDG Alpes Haute Provence",
                            },
                        },
                        {
                            "code": "2",
                            "libelle": "Accéder à  une connexion internet",
                            "valeur": "NON_ABORDE",
                            "dateExploration": None,
                            "agent": None,
                        },
                        {
                            "code": "3",
                            "libelle": "Maîtriser les fondamentaux du numérique",
                            "valeur": "NON_ABORDE",
                            "dateExploration": None,
                            "agent": None,
                        },
                    ],
                },
                "besoin": {
                    "code": "7",
                    "libelle": "Connaître et utiliser les services numériques",
                    "valeur": "BESOIN",
                    "dateExploration": "2021-05-17T16:47:11.000+02:00",
                    "agent": {
                        "id": "ertc8250",
                        "nom": "Dupont",
                        "prenom": "Fernande",
                        "structure": "CDG Alpes Haute Provence",
                    },
                },
            },
        },
    },
}
