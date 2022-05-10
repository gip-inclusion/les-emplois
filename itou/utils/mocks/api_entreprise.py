import uuid


# Result for a call to: https://api.insee.fr/token
INSEE_API_RESULT_MOCK = {
    "access_token": str(uuid.uuid4()),
}

# Result for a call to: https://api.insee.fr/entreprises/sirene/V3/siret/26570134200148?masquerValeursNulles=true
ETABLISSEMENT_API_RESULT_MOCK = {
    "header": {"statut": 200, "message": "ok"},
    "etablissement": {
        "siren": "265701342",
        "nic": "00148",
        "siret": "26570134200148",
        "statutDiffusionEtablissement": "O",
        "dateCreationEtablissement": "2004-02-01",
        "trancheEffectifsEtablissement": "12",
        "anneeEffectifsEtablissement": "2019",
        "dateDernierTraitementEtablissement": "2021-10-27T08:13:02",
        "etablissementSiege": True,
        "nombrePeriodesEtablissement": 3,
        "uniteLegale": {
            "etatAdministratifUniteLegale": "A",
            "statutDiffusionUniteLegale": "O",
            "dateCreationUniteLegale": "1975-01-01",
            "categorieJuridiqueUniteLegale": "7361",
            "denominationUniteLegale": "CENTRE COMMUNAL D'ACTION SOCIALE",
            "sigleUniteLegale": "CCAS",
            "activitePrincipaleUniteLegale": "88.99B",
            "nomenclatureActivitePrincipaleUniteLegale": "NAFRev2",
            "caractereEmployeurUniteLegale": "O",
            "trancheEffectifsUniteLegale": "21",
            "anneeEffectifsUniteLegale": "2019",
            "nicSiegeUniteLegale": "00148",
            "dateDernierTraitementUniteLegale": "2021-10-27T08:13:02",
            "categorieEntreprise": "PME",
            "anneeCategorieEntreprise": "2019",
        },
        "adresseEtablissement": {
            "complementAdresseEtablissement": "22-24",
            "numeroVoieEtablissement": "22",
            "typeVoieEtablissement": "RUE",
            "libelleVoieEtablissement": "DU WAD BILLY",
            "codePostalEtablissement": "57000",
            "libelleCommuneEtablissement": "METZ",
            "codeCommuneEtablissement": "57463",
        },
        "adresse2Etablissement": {},
        "periodesEtablissement": [
            {
                "dateDebut": "2008-01-01",
                "etatAdministratifEtablissement": "A",
                "changementEtatAdministratifEtablissement": False,
                "changementEnseigneEtablissement": False,
                "changementDenominationUsuelleEtablissement": False,
                "activitePrincipaleEtablissement": "88.99B",
                "nomenclatureActivitePrincipaleEtablissement": "NAFRev2",
                "changementActivitePrincipaleEtablissement": True,
                "caractereEmployeurEtablissement": "O",
                "changementCaractereEmployeurEtablissement": False,
            },
            {
                "dateFin": "2007-12-31",
                "dateDebut": "2004-12-25",
                "etatAdministratifEtablissement": "A",
                "changementEtatAdministratifEtablissement": False,
                "changementEnseigneEtablissement": False,
                "changementDenominationUsuelleEtablissement": False,
                "activitePrincipaleEtablissement": "85.3K",
                "nomenclatureActivitePrincipaleEtablissement": "NAFRev1",
                "changementActivitePrincipaleEtablissement": True,
                "caractereEmployeurEtablissement": "O",
                "changementCaractereEmployeurEtablissement": True,
            },
            {
                "dateFin": "2004-12-24",
                "dateDebut": "2004-02-01",
                "etatAdministratifEtablissement": "A",
                "changementEtatAdministratifEtablissement": False,
                "changementEnseigneEtablissement": False,
                "changementDenominationUsuelleEtablissement": False,
                "changementActivitePrincipaleEtablissement": False,
                "changementCaractereEmployeurEtablissement": False,
            },
        ],
    },
}
