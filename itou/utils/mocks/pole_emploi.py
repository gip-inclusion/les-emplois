"""
Result for a call to:
https://entreprise.api.gouv.fr/v2/etablissements/26570134200148
"""

POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_KNOWN_MOCK = {
    "idNationalDE": "ruLuawDxNzERAFwxw6Na4V8A8UCXg6vXM_WKkx5j8UQ",
    "codeSortie": "S001",
    "certifDE": False,
}

POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_UNKNOWN_MOCK = {
    "idNationalDE": "",
    "codeSortie": "S000",
    "certifDE": False,
}

POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_MANY_RESULTS_MOCK = {
    "idNationalDE": "",
    "codeSortie": "S002",
    "certifDE": False,
}

POLE_EMPLOI_RECHERCHE_INDIVIDU_CERTIFIE_API_RESULT_ERROR_MOCK = {
    "idNationalDE": "",
    "codeSortie": "R010",
    "certifDE": False,
}
