from allauth.socialaccount.providers.base import ProviderAccount
from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider
from django.conf import settings


# OIDC scopes

BASIC_SCOPES = [
    # API Se connecter avec Pôle emploi (individu) v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-individu-v1.html
    "openid",
    "api_peconnect-individuv1",
    "email",
    "profile",
]

EXTRA_SCOPES = [
    # API Coordonnées v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-coordonnees-v1.html
    "api_peconnect-coordonneesv1",
    "coordonnees",
    # API Statut v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-statut-v1.html
    "api_peconnect-statutv1",
    "statut",
    # API Date de naissance v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-datenaissance-v1.html
    "api_peconnect-datenaissancev1",
    "datenaissance",
    # API Indemnisations v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-indemnisations-v1.html
    "api_peconnect-indemnisationsv1",
    "indemnisation",
    # API Expériences professionnelles v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-experiences-professionnelles.html
    # "api_peconnect-experiencesv1",
    # "pfcexperiences",
    # API Expériences déclarées par l’Employeur v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-exp-declarees-v1.html
    # "api_peconnect-experiencesprofessionellesdeclareesparlemployeurv1",
    # "passeprofessionnel",
    # API Formations professionnelles v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-formations-professionnelles.html
    "api_peconnect-formationsv1",
    "pfcformations",
    "pfcpermis",
    # API Compétences professionnelles v2
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-competence-v2-1.html
    # "api_peconnect-competencesv2",
    # "pfccompetences",
    # "pfclangues",
    # "pfccentresinteret",
]


class PEAMUProvider(OAuth2Provider):
    id = "peamu"
    name = "PEAMU"
    account_class = ProviderAccount

    def get_default_scope(self):
        client_id = settings.SOCIALACCOUNT_PROVIDERS["peamu"]["APP"]["client_id"]
        scope = [f"application_{client_id}"] + BASIC_SCOPES + EXTRA_SCOPES
        return scope

    def get_auth_params(self, request, action):
        ret = super().get_auth_params(request, action)
        ret["realm"] = "/individu"
        return ret

    def extract_uid(self, data):
        return str(data["sub"])

    def extract_common_fields(self, data):
        return dict(email=data.get("email"), last_name=data.get("family_name"), first_name=data.get("given_name"))
