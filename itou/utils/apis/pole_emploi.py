import logging

import httpx
from django.conf import settings

from itou.job_applications.models import JobApplication
from itou.siaes.models import Siae


logger = logging.getLogger(__name__)


class PoleEmploiIndividu:
    def __init__(self, first_name, last_name, birthdate, nir):
        self.first_name = first_name.upper()
        self.last_name = last_name.upper()
        self.birthdate = birthdate.strftime("%Y-%m-%d")
        self.nir = nir

    def is_valid(self):
        return self.first_name != "" and self.last_name != "" and len(self.nir) == 13 and self.birthdate != ""

    def as_api_params(self):
        """converts the user data for use in the RechercheIndividuCertifie API"""
        return {
            "nirCertifie": self.nir,
            "nomNaissance": self.last_name,
            "prenom": self.first_name,
            "dateNaissance": self.birthdate,
        }


class PoleEmploiRechercheIndividuCertifieAPI:
    """
    So we post this :
    {
        "nirCertifie":"1800813800217",
        "nomNaissance":"MARTIN",
        "prenom":"LAURENT",
        "dateNaissance":"1979-07-25"
    }

    and as an output we receive an "individual":

    {
        "idNationalDE":"",
        "codeSortie": "R010",
        "certifDE":false
    }

    """

    CODE_SORTIE_MAPPING = {
        "S000": "Aucun individu trouvé",
        "S001": "Individu trouvé",
        "S002": "Plusieurs individu trouvés",
        "R010": "NIR Certifié absent",
        "R011": "NIR Certifié incorrect",
        "R020": "Nom de naissance absente",
        "R021": "Nom de naissance incorrect",
        "R030": "Prénom absent",
        "R031": "Prénom incorrect",
        "R040": "Date de naissance absente",
        "R041": "Date de naissance incorrecte",
        "R042": "Date de naissance invalide",
    }

    def __init__(self, params, token):
        """
        Token should be in the form "Bearer token_value".
        It is provided by the `get_access_token` helper.
        """
        self.data, self.error = self.post(params, token)

    def post(self, individu, token):

        data = None
        error = None

        url = f"{settings.API_ESD_BASE_URL}/rechercheindividucertifie/v1/rechercheIndividuCertifie"
        headers = {"Authorization": token}

        try:
            r = httpx.post(url, json=individu.as_api_params(), headers=headers)
            data = r.json()
            # we can’t use `raise_for_error` since actual data are stored with status code 4xx
            if r.status_code not in [200, 400, 401, 404, 429]:
                raise ValueError("Invalid user data sent")

        except httpx.HTTPError as e:
            logger.error(
                "Error while fetching `%s` with %s, got %s", url, individu.as_api_params(), e.response.content
            )
            error = "Unable to fetch user data."
        except ValueError:
            logger.error("Error while fetching `%s` with %s, got %s", url, individu.as_api_params(), r.content)
            error = "Unable to fetch user data."

        return data, error

    @property
    def is_valid(self):
        return self.data is not None and self.code_sortie == "S001"

    @property
    def id_national_demandeur(self):
        """Identifiant national Pôle Emploi chiffré"""
        return self.data["idNationalDE"]

    @property
    def code_sortie(self):
        """
        A value sorted in CODE_SORTIE_MAPPING
        """
        return self.data["codeSortie"]

    @property
    def certification_demandeur(self):
        """
        Niveau de certification du DE dans la base PE
        true ou false (false par défaut ou si le DE n'est pas trouvé)
        """
        return self.data["certifDE"]


class PoleEmploiMiseAJourPass:

    ORIGIN_DEMANDEUR = "DEMA"
    ORIGIN_PRESCRIPTEUR = "PRES"
    ORIGIN_EMPLOYEUR = "EMPL"

    PASS_APPROVED = "A"
    PASS_REFUSED = "R"

    DATE_FORMAT = "%Y-%m-%d"

    def kind(siae_kind):
        # Valeurs possibles coté PE :
        # « 836 – IAE ITOU ACI »
        # « 837 – IAE ITOU AI »
        # « 838 – IAE ITOU EI »
        # « 839 – IAE ITOU ETT »
        # « 840 – IAE ITOU EIT »
        mapping = {
            Siae.KIND_EI: 838,
            Siae.KIND_AI: 837,
            Siae.KIND_ACI: 836,
            Siae.KIND_ACIPHC: 837,
            Siae.KIND_ETTI: 839,
            Siae.KIND_EITI: 840,
            Siae.KIND_GEIQ: 838,
            Siae.KIND_EA: 838,
            Siae.KIND_EATT: 840,
        }

        if siae_kind not in mapping.keys():
            raise ValueError("Siae kind is not handled by pole emploi")

        return mapping[siae_kind]

    def sender_kind(sender_kind):
        sender_kind_mapping = {
            JobApplication.SENDER_KIND_JOB_SEEKER: PoleEmploiMiseAJourPass.ORIGIN_DEMANDEUR,
            JobApplication.SENDER_KIND_PRESCRIBER: PoleEmploiMiseAJourPass.ORIGIN_PRESCRIPTEUR,
            JobApplication.SENDER_KIND_SIAE_STAFF: PoleEmploiMiseAJourPass.ORIGIN_EMPLOYEUR,
        }

        if sender_kind not in sender_kind_mapping.keys():
            raise ValueError("sender kind is not handled by pole emploi")

        return sender_kind_mapping[sender_kind]

    def refused_parameters(encrypted_identifier, siae):
        """
        The necessary parameters to notify Pole Emploi of a refusal
        """
        return {
            "idNational": encrypted_identifier,
            "statutReponsePassIAE": PoleEmploiMiseAJourPass.PASS_REFUSED,
            "origineCandidature": PoleEmploiMiseAJourPass.sender_kind(siae),
        }

    def approved_parameters(encrypted_identifier, siae, approval):
        """
        The necessary parameters to notify Pole Emploi that a Pass has been granted
        """
        return {
            "idNational": encrypted_identifier,
            "statutReponsePassIAE": PoleEmploiMiseAJourPass.PASS_APPROVED,
            "typeSIAE": PoleEmploiMiseAJourPass.kind(siae),
            "dateDebutPassIAE": PoleEmploiMiseAJourPass.approval.start_at.strftime(
                PoleEmploiMiseAJourPass.DATE_FORMAT
            ),
            "dateFinPassIAE": PoleEmploiMiseAJourPass.approval.end_at.strftime(PoleEmploiMiseAJourPass.DATE_FORMAT),
            "numPassIAE": approval.number,
            "numSIRETsiae": siae.siret,
            "origineCandidature": PoleEmploiMiseAJourPass.sender_kind(siae),
        }


class PoleEmploiMiseAJourPassIAEAPI:
    USE_PRODUCTION_ROUTE = "prod"
    USE_SANDBOX_ROUTE = "sandbox"

    def __init__(self, params, token, api_production_or_sandbox):
        """
        Token should be in the form "Bearer token_value".
        It is provided by the `get_access_token` helper.

        `params` should be generated with PoleEmploiMiseAJourPass.approved_parameters
        or PoleEmploiMiseAJourPass.approved_parameters,

        api_production_or_sandbox is a sad remnant of the tests in the recette environment.
        It mightp be useful in pre-production, as well as for re-performing tests.
        """
        self.data, self.error = self.post(params, token, api_production_or_sandbox)

    def post(self, params, token, api_production_or_sandbox):

        data = None
        error = None

        # The production URL
        url = f"{settings.API_ESD_BASE_URL}/maj-pass-iae/v1/passIAE/miseAjour"
        if api_production_or_sandbox == self.USE_SANDBOX_ROUTE:
            # The test URL in recette, sandboxed mode
            url = f"{settings.API_ESD_BASE_URL}/testmaj-pass-iae/v1/passIAE/miseAjour"

        headers = {"Authorization": token, "Content-Type": "application/json"}

        try:
            r = httpx.post(url, json=params, headers=headers)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            if e.response.status_code == 401:
                error = "CF CodeSortie Erreur pour voir le contrôle correspondant"
            if e.response.status_code == 404:
                # surprise !? PE's authentication layer can trigger 404
                # if the scope does not allow access to this API
                error = "Erreur d'authentification"
            else:
                # In general when input data cannot be processed, a 500 is returned
                logger.error("Error while fetching `%s`: %s", url, e)
                error = "Unable to update data."

        self.data = data

        return data, error

    @property
    def code_sortie(self):
        """
        A 4 letter value in the form "Sxxx":
         - S001 to S043 for errors
         - S100 for success
        """
        return self.data["codeSortie"] if self.data is not None else ""
