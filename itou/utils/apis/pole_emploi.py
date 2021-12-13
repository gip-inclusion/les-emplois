import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from django.conf import settings

from itou.siaes.models import Siae  # noqa


logger = logging.getLogger(__name__)


class PoleEmploiMiseAJourPassIAEException(Exception):
    """
    The mise a jour process has errors in 2 locations:
     - http response code: can be 401, 400…
     - we can have non-200 response code, plus sometimes some details in the json response
    """

    def __init__(self, http_code, response_code=""):
        super().__init__()
        self.http_code = http_code
        self.response_code = response_code


class PoleEmploiIndividu:
    def __init__(self, first_name: str, last_name: str, birthdate, nir: str):
        self.first_name = first_name.upper()
        self.last_name = last_name.upper()
        self.birthdate = birthdate.strftime("%Y-%m-%d")
        self.nir = nir

    @classmethod
    def from_job_seeker(cls, job_seeker):
        return PoleEmploiIndividu(job_seeker.first_name, job_seeker.last_name, job_seeker.birth_date, job_seeker.nir)

    def is_valid(self):
        return self.first_name != "" and self.last_name != "" and len(self.nir) == 13 and self.birthdate != ""

    def as_api_params(self):
        """converts the user data for use in the RechercheIndividuCertifie API"""
        nir = self.nir
        if nir is not None and len(nir) > 13:
            # Pole emploi only wants the first 13 digits
            nir = nir[:13]

        return {
            "nirCertifie": nir,
            "nomNaissance": self.last_name,
            "prenom": self.first_name,
            "dateNaissance": self.birthdate,
        }


@dataclass
class PoleEmploiIndividuResult:
    # Identifiant national Pôle Emploi chiffré
    id_national_demandeur: str
    # A value sorted in CODE_SORTIE_MAPPING
    code_sortie: str
    # Niveau de certification du DE dans la base PE
    # true ou false (false par défaut ou si le DE n'est pas trouvé)
    certif_de: str

    def is_valid(self):
        return self.code_sortie == "S001"

    @staticmethod
    def from_data(data):
        if data is not None and type(data) == dict:
            return PoleEmploiIndividuResult(
                data.get("idNationalDE", ""), data.get("codeSortie", ""), data.get("certifDE", "")
            )
        return None


CODE_SORTIE_MAPPING_RECHERCHE_INDIVIDU_CERTIFIE = {
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


def extract_code_sortie(data) -> str:
    if data is not None and type(data) == dict:
        return data.get("codeSortie", "")
    return ""


def recherche_individu_certifie_api(individu: PoleEmploiIndividu, token: str) -> Optional[PoleEmploiIndividuResult]:
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
    url = f"{settings.API_ESD_BASE_URL}/rechercheindividucertifie/v1/rechercheIndividuCertifie"
    headers = {"Authorization": token}

    try:
        r = httpx.post(url, json=individu.as_api_params(), headers=headers)
        data = r.json()
        # we can’t use `raise_for_error` since actual data are stored with status code 4xx
        # if r.status_code not in [200, 400, 401, 404, 429]
        # for now we only care about 200 (-> successful search, someone may have been found)
        if r.status_code != 200:
            # The only thing we care about is http code 200
            raise PoleEmploiMiseAJourPassIAEException(r.status_code, extract_code_sortie(data))
        return PoleEmploiIndividuResult.from_data(data)
    except httpx.HTTPError as e:
        raise PoleEmploiMiseAJourPassIAEException(e.response.status_code)
    except ValueError:
        raise PoleEmploiMiseAJourPassIAEException(r.status_code)
    # should not happen, but we never want to miss an exception
    raise PoleEmploiMiseAJourPassIAEException("no response code")


# class PoleEmploiMiseAJourPass:
#
#     ORIGIN_DEMANDEUR = "DEMA"
#     ORIGIN_PRESCRIPTEUR = "PRES"
#     ORIGIN_EMPLOYEUR = "EMPL"
#
#     PASS_APPROVED = "A"
#     PASS_REFUSED = "R"
#
#     DATE_FORMAT = "%Y-%m-%d"
#
#     def kind(siae_kind):
#         # Valeurs possibles coté PE :
#         # « 836 – IAE ITOU ACI »
#         # « 837 – IAE ITOU AI »
#         # « 838 – IAE ITOU EI »
#         # « 839 – IAE ITOU ETT »
#         # « 840 – IAE ITOU EIT »
#         mapping = {
#             Siae.KIND_EI: 838,
#             Siae.KIND_AI: 837,
#             Siae.KIND_ACI: 836,
#             Siae.KIND_ACIPHC: 837,
#             Siae.KIND_ETTI: 839,
#             Siae.KIND_EITI: 840,
#             Siae.KIND_GEIQ: 838,
#             Siae.KIND_EA: 838,
#             Siae.KIND_EATT: 840,
#         }
#
#         if siae_kind not in mapping.keys():
#             raise ValueError("Siae kind is not handled by pole emploi")
#
#         return mapping[siae_kind]
#
#     @staticmethod
#     def sender_kind(sender_kind):
#         # raise "Todo: fix me, I cause a circular reference"
#         # sender_kind_mapping = {
#         #     JobApplication.SENDER_KIND_JOB_SEEKER: PoleEmploiMiseAJourPass.ORIGIN_DEMANDEUR,
#         #     JobApplication.SENDER_KIND_PRESCRIBER: PoleEmploiMiseAJourPass.ORIGIN_PRESCRIPTEUR,
#         #     JobApplication.SENDER_KIND_SIAE_STAFF: PoleEmploiMiseAJourPass.ORIGIN_EMPLOYEUR,
#         # }
#
#         # if sender_kind not in sender_kind_mapping.keys():
#         #     raise ValueError("sender kind is not handled by pole emploi")
#
#         # return sender_kind_mapping[sender_kind]
#         return PoleEmploiMiseAJourPass.ORIGIN_DEMANDEUR
#
#     @staticmethod
#     def refused_parameters(encrypted_identifier, siae):
#         """
#         The necessary parameters to notify Pole Emploi of a refusal
#         """
#         return {
#             "idNational": encrypted_identifier,
#             "statutReponsePassIAE": PoleEmploiMiseAJourPass.PASS_REFUSED,
#             "origineCandidature": PoleEmploiMiseAJourPass.sender_kind(siae),
#         }
#
#     @staticmethod
#     def accepted_parameters(encrypted_identifier, siae, approval):
#         """
#         The necessary parameters to notify Pole Emploi that a Pass has been granted
#         """
#         return {
#             "idNational": encrypted_identifier,
#             "statutReponsePassIAE": PoleEmploiMiseAJourPass.PASS_APPROVED,
#             "typeSIAE": PoleEmploiMiseAJourPass.kind(siae),
#             "dateDebutPassIAE": approval.start_at.strftime(PoleEmploiMiseAJourPass.DATE_FORMAT),
#             "dateFinPassIAE": approval.end_at.strftime(PoleEmploiMiseAJourPass.DATE_FORMAT),
#             "numPassIAE": approval.number,
#             "numSIRETsiae": siae.siret,
#             "origineCandidature": PoleEmploiMiseAJourPass.sender_kind(siae),
#         }
#
# USE_PRODUCTION_ROUTE = "prod"
# USE_SANDBOX_ROUTE = "sandbox"
#
# def code_sortie_maj(data):
#     """
#     A 4 letter value in the form "Sxxx":
#      - S001 to S043 for errors
#      - S100 for success
#     """
#     return data.get("codeSortie") if data is not None else ""
#
# def mise_a_jour_pass_iae(params, token, api_production_or_sandbox):
#     data = None
#     error = None
#
#     # The production URL
#     url = f"{settings.API_ESD_BASE_URL}/maj-pass-iae/v1/passIAE/miseAjour"
#     if api_production_or_sandbox == USE_SANDBOX_ROUTE:
#         # The test URL in recette, sandboxed mode
#         url = f"{settings.API_ESD_BASE_URL}/testmaj-pass-iae/v1/passIAE/miseAjour"
#
#     headers = {"Authorization": token, "Content-Type": "application/json"}
#
#     try:
#         r = httpx.post(url, json=params, headers=headers)
#         r.raise_for_status()
#         data = r.json()
#     except httpx.HTTPError as e:
#         if e.response.status_code == 401:
#             error = f"Error with code: {code_sortie_maj(data)}"
#         if e.response.status_code == 404:
#             # surprise !? PE's authentication layer can trigger 404
#             # if the scope does not allow access to this API
#             error = "Authentication error"
#         else:
#             # In general when input data cannot be processed, a 500 is returned
#             logger.error("Error while fetching `%s`: %s", url, e)
#             error = "Unable to update data."
#
#     return data, error
