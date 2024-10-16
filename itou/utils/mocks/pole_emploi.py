API_RECHERCHE_RESULT_KNOWN = {
    "idNationalDE": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
    "codeSortie": "S001",
    "certifDE": False,
}

API_RECHERCHE_MANY_RESULTS = {
    "idNationalDE": "",
    "codeSortie": "S002",
    "certifDE": False,
}

API_RECHERCHE_ERROR = {
    "idNationalDE": "",
    "codeSortie": "R010",
    "certifDE": False,
}

API_MAJPASS_RESULT_OK = {
    "codeSortie": "S000",
    "idNational": "some_id_national",
    "message": "Pass IAE prescrit",
}

API_MAJPASS_RESULT_ERROR = {
    "codeSortie": "S022",
    "idNational": "some_id_national",
    "message": "SD non installé : : Refus du PASS IAE",
}

API_REFERENTIEL_NATURE_CONTRATS = [
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

API_OFFRES = [
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
    },
]

API_APPELLATIONS = [
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
