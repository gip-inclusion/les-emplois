"""
Result for a call to:
https://entreprise.api.gouv.fr/v2/etablissements/26570134200148
"""

ETABLISSEMENT_API_RESULT_MOCK = {
    "etablissement": {
        "siege_social": True,
        "siret": "26570134200148",
        "naf": "8899B",
        "libelle_naf": "Action sociale sans hébergement n.c.a.",
        "date_mise_a_jour": 1561374852,
        "tranche_effectif_salarie_etablissement": {
            "de": 20,
            "a": 49,
            "code": "12",
            "date_reference": "2017",
            "intitule": "20 à 49 salariés",
        },
        "date_creation_etablissement": 1075590000,
        "region_implantation": {"code": "44", "value": "Grand Est"},
        "commune_implantation": {"code": "57463", "value": "Metz"},
        "pays_implantation": {"code": "FR", "value": "FRANCE"},
        "diffusable_commercialement": True,
        "enseigne": None,
        "adresse": {
            "l1": "CENTRE COMMUNAL D'ACTION SOCIALE",
            "l2": None,
            "l3": "22-24",
            "l4": "22 RUE DU WAD BILLY",
            "l5": None,
            "l6": "57000 METZ",
            "l7": "FRANCE",
            "numero_voie": "22",
            "type_voie": "RUE",
            "nom_voie": "DU WAD BILLY",
            "complement_adresse": "22-24",
            "code_postal": "57000",
            "localite": "METZ",
            "code_insee_localite": "57463",
            "cedex": None,
        },
        "etat_administratif": {"value": "A", "date_fermeture": None},
    },
    "gateway_error": False,
}
