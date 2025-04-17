import enum

from django.conf import settings

from itou.eligibility.enums import AdministrativeCriteriaKind


ENDPOINTS = {
    AdministrativeCriteriaKind.RSA: f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active",
    AdministrativeCriteriaKind.AAH: f"{settings.API_PARTICULIER_BASE_URL}v2/allocation-adulte-handicape",
    AdministrativeCriteriaKind.PI: f"{settings.API_PARTICULIER_BASE_URL}v2/allocation-soutien-familial",
}


class ResponseKind(enum.Enum):
    CERTIFIED = "certified"
    NOT_CERTIFIED = "not_certified"
    NOT_FOUND = "not_found"
    PROVIDER_UNKNOWN_ERROR = "provider_unknown_error"


RESPONSES = {
    AdministrativeCriteriaKind.RSA: {
        # https://github.com/etalab/siade_staging_data/blob/develop/payloads/api_particulier_v2_cnav_revenu_solidarite_active/200_beneficiaire_majoration.yaml
        ResponseKind.CERTIFIED: {
            "status": "beneficiaire",
            "majoration": True,
            "dateDebut": "2024-08-01",
            "dateFin": None,
        },
        ResponseKind.NOT_CERTIFIED: {
            "status": "non_beneficiaire",
            "majoration": None,
            "dateDebut": None,
            "dateFin": None,
        },
        # https://github.com/etalab/siade_staging_data/blob/develop/payloads/api_particulier_v2_cnav_revenu_solidarite_active/404.yaml
        ResponseKind.NOT_FOUND: {
            "error": "not_found",
            "reason": "Dossier allocataire inexistant. Le document ne peut être édité.",
            "message": "Dossier allocataire inexistant. Le document ne peut être édité.",
        },
        ResponseKind.PROVIDER_UNKNOWN_ERROR: {
            "error": "provider_unknown_error",
            "reason": (
                "La réponse retournée par le fournisseur de données est invalide et inconnue de notre service. "
                "L'équipe technique a été notifiée de cette erreur pour investigation."
            ),
            "message": (
                "La réponse retournée par le fournisseur de données est invalide et inconnue de notre service. "
                "L'équipe technique a été notifiée de cette erreur pour investigation."
            ),
        },
    },
    AdministrativeCriteriaKind.AAH: {
        # https://particulier.api.gouv.fr/developpeurs/openapi#tag/Prestations-sociales/paths/~1api~1v2~1allocation-adulte-handicape/get
        ResponseKind.CERTIFIED: {"status": "beneficiaire", "dateDebut": "2024-08-01"},
        ResponseKind.NOT_CERTIFIED: {"status": "non_beneficiaire", "dateDebut": None, "dateFin": None},
    },
    AdministrativeCriteriaKind.PI: {
        # https://particulier.api.gouv.fr/developpeurs/openapi#tag/Prestations-sociales/paths/~1api~1v2~1allocation-soutien-familial/get
        ResponseKind.CERTIFIED: {"status": "beneficiaire", "dateDebut": "2024-08-01"},
        ResponseKind.NOT_CERTIFIED: {"status": "non_beneficiaire", "dateDebut": None, "dateFin": None},
    },
}
