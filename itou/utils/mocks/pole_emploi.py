"""
Result for a call to:
https://entreprise.api.gouv.fr/v2/etablissements/26570134200148
"""

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
    "message": "SD non installé : : Refus du PASS IAE",
}
