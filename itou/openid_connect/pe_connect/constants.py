from django.conf import settings


PE_BASIC_SCOPES = [
    # API Se connecter avec Pôle emploi (individu) v1
    # https://www.emploi-store-dev.fr/portail-developpeur-cms/home/catalogue-des-api/documentation-des-api/api/api-pole-emploi-connect/api-peconnect-individu-v1.html
    "openid",
    "api_peconnect-individuv1",
    "email",
    "profile",
]

PE_EXTRA_SCOPES = [
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

PE_CONNECT_SCOPES = " ".join(PE_BASIC_SCOPES + PE_EXTRA_SCOPES)

PE_CONNECT_ENDPOINT_AUTHORIZE = f"{settings.PEAMU_AUTH_BASE_URL}/connexion/oauth2/authorize"
PE_CONNECT_ENDPOINT_TOKEN = f"{settings.PEAMU_AUTH_BASE_URL}/connexion/oauth2/access_token"
PE_CONNECT_ENDPOINT_USERINFO = f"{settings.API_ESD['BASE_URL']}/peconnect-individu/v1/userinfo"
PE_CONNECT_ENDPOINT_LOGOUT = f"{settings.PEAMU_AUTH_BASE_URL}/compte/deconnexion"

PE_CONNECT_SESSION_TOKEN = "PE_ID_TOKEN"
PE_CONNECT_SESSION_STATE = "PE_STATE"
