import enum

from itou.eligibility.enums import AdministrativeCriteriaKind


class ResponseKind(enum.Enum):
    CERTIFIED = "certified"
    NOT_CERTIFIED = "not_certified"
    NOT_FOUND = "not_found"
    PROVIDER_UNKNOWN_ERROR = "provider_unknown_error"


RESPONSES = {
    AdministrativeCriteriaKind.RSA: {
        # https://particulier.api.gouv.fr/developpeurs/openapi-v3#tag/Statut-Revenu-Solidarite-Active-(RSA)
        ResponseKind.CERTIFIED: {
            "data": {
                "est_beneficiaire": True,
                "avec_majoration": True,
                "date_debut_droit": "2024-08-01",
            }
        },
        ResponseKind.NOT_CERTIFIED: {
            "data": {
                "est_beneficiaire": False,
                "avec_majoration": None,
                "date_debut_droit": None,
            },
        },
        ResponseKind.NOT_FOUND: {
            "errors": [
                {
                    "code": "10003",
                    "title": "Dossier allocataire absent MSA",
                    "detail": "Le dossier allocataire n'a pas été trouvé auprès de la MSA.",
                    "source": None,
                    "meta": {"provider": "MSA"},
                },
            ],
        },
        ResponseKind.PROVIDER_UNKNOWN_ERROR: {
            "errors": [
                {
                    "code": "37999",
                    "title": "Erreur inconnue du fournisseur de données",
                    "detail": (
                        "La réponse retournée par le fournisseur de données est invalide et inconnue de notre "
                        "service. L'équipe technique a été notifiée de cette erreur pour investigation."
                    ),
                    "source": None,
                    "meta": {"provider": "CNAV"},
                },
            ],
        },
    },
    AdministrativeCriteriaKind.AAH: {
        # https://particulier.api.gouv.fr/developpeurs/openapi-v3#tag/Statut-Allocation-Adulte-Handicape-(AAH)
        ResponseKind.CERTIFIED: {"data": {"est_beneficiaire": True, "date_debut_droit": "2024-08-01"}},
        ResponseKind.NOT_CERTIFIED: {"data": {"est_beneficiaire": False, "date_debut_droit": None}},
    },
    AdministrativeCriteriaKind.PI: {
        # https://particulier.api.gouv.fr/developpeurs/openapi-v3#tag/Statut-Allocation-Soutien-Familial-(ASF)
        ResponseKind.CERTIFIED: {"data": {"est_beneficiaire": True, "date_debut_droit": "2024-08-01"}},
        ResponseKind.NOT_CERTIFIED: {"data": {"est_beneficiaire": False, "date_debut_droit": None}},
    },
}
