import logging
from dataclasses import dataclass
from typing import Optional

import httpx
from django.conf import settings

from itou.siaes.models import Siae


logger = logging.getLogger(__name__)

# The values for the pass status in the mise à jour API
POLE_EMPLOI_PASS_APPROVED = "A"
POLE_EMPLOI_PASS_REFUSED = "R"

DATE_FORMAT = "%Y-%m-%d"
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


class PoleEmploiMiseAJourPassIAEException(Exception):
    """
    The mise a jour process has errors in 2 locations:
     - http response code: can be 401, 400…
     - we can have non-200 response code, plus sometimes some details in the json response
    So we store whatever we may have
    """

    def __init__(self, http_code, message=""):
        super().__init__()
        self.http_code = http_code
        self.response_code = message


class PoleEmploiIndividu:
    def __init__(self, first_name: str, last_name: str, birthdate, nir: str):
        self.first_name = first_name.upper()
        self.last_name = last_name.upper()
        self.birthdate = birthdate.strftime("%Y-%m-%d")
        self.nir = nir

    @classmethod
    def from_job_seeker(cls, job_seeker):
        if job_seeker is not None:
            nir = "" if job_seeker.nir is None else job_seeker.nir[0:13]
            return PoleEmploiIndividu(job_seeker.first_name, job_seeker.last_name, job_seeker.birthdate, nir)
        return None

    def is_valid(self):
        return self.first_name != "" and self.last_name != "" and len(self.nir) == 13 and self.birthdate != ""

    def as_api_params(self):
        """converts the user data for use in the RechercheIndividuCertifie API"""
        nir = self.nir
        if nir is not None and len(nir) > 13:
            # Pole emploi only wants the first 13 digits
            nir = nir[0:13]

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
        # This specific value is provided by Pole Emploi as part of their API spec
        CODE_SORTIE_INDIVIDU_TROUVE = "S001"
        return self.code_sortie == CODE_SORTIE_INDIVIDU_TROUVE

    @staticmethod
    def from_data(data):
        if data is not None and type(data) == dict:
            return PoleEmploiIndividuResult(
                data.get("idNationalDE", ""), data.get("codeSortie", ""), data.get("certifDE", "")
            )
        return None


def extract_code_sortie(data) -> str:
    """
    Returns a 4 letter value in the form "Sxxx".
    This is used both for recherche individu and mise à jour pass IAE.
    Most of the time we’ll only care about the success code (S000).
    We store non-success code in the logs for statistics, but there’s nothing we can do to improve the situation:
    They may stem from data mismatch on PE’s end, which are business-related, not tied to a technical issue
    """
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


def mise_a_jour_pass_iae(job_application, pass_approved_code, encrypted_identifier, token):
    """
    We post some data (see _mise_a_jour_parameters), and as an output we get a JSON response:
    {'codeSortie': 'S000', 'idNational': 'some identifier', 'message': 'Pass IAE prescrit'}
    The only valid result is HTTP 200 + codeSortie = "S000".
    Everything else (other HTTP code, or different code_sortie) means that our notification has been discarded.
    Here is an excerpt of those status codes ; there is nothing we can do to fix it on our end.
        S008 Individu radié
        S013 Individu sans référent de suivi principal
        S015 Individu avec Suivi Délégué déjà en cours
        S017 Individu en suivi CRP (donc non EDS)
        S032 Organisme ou structure inexistant dans le référentiel Partenaire
        S036 Lien inexistant entre structure et organisme
    """
    CODE_SORTIE_PASS_IAE_PRESCRIT = "S000"  # noqa constant that comes from Pole Emploi’s documentation

    # The production URL
    url = f"{settings.API_ESD_BASE_URL}/maj-pass-iae/v1/passIAE/miseAjour"
    if settings.API_ESD_MISE_A_JOUR_PASS_MODE != "production":
        # The test URL in recette, sandboxed mode
        url = f"{settings.API_ESD_BASE_URL}/testmaj-pass-iae/v1/passIAE/miseAjour"  # noqa
    url = f"{settings.API_ESD_BASE_URL}/testmaj-pass-iae/v1/passIAE/miseAjour"  # noqa

    headers = {"Authorization": token, "Content-Type": "application/json"}  # noqa

    try:
        params = _mise_a_jour_parameters(encrypted_identifier, job_application, pass_approved_code)
        r = httpx.post(url, json=params, headers=headers)
        data = r.json()
        code_sortie = extract_code_sortie(data)
        # The only way the process can be entirely realized is with
        # code HTTP 200 + a specific code sortie
        if r.status_code != 200 or code_sortie != CODE_SORTIE_PASS_IAE_PRESCRIT:
            raise PoleEmploiMiseAJourPassIAEException(r.status_code, code_sortie)
        return True
    except httpx.HTTPError as e:
        raise PoleEmploiMiseAJourPassIAEException(e.response.status_code)

    raise PoleEmploiMiseAJourPassIAEException("undetected failure to update")


def _mise_a_jour_siae_kind_param(siae_kind):
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
    if siae_kind in mapping:
        return mapping[siae_kind]
    # The param has to be set, so we need to pick a default value
    return mapping[Siae.KIND_EI]


def _mise_a_jour_sender_kind_param(sender_kind):
    # we need to import here in order to avoid circular reference.
    # We need this import to avoid duplication of the constants
    from itou.job_applications.models import JobApplication

    ORIGIN_DEMANDEUR = "DEMA"
    ORIGIN_PRESCRIPTEUR = "PRES"
    ORIGIN_EMPLOYEUR = "EMPL"
    sender_kind_mapping = {
        JobApplication.SENDER_KIND_JOB_SEEKER: ORIGIN_DEMANDEUR,
        JobApplication.SENDER_KIND_PRESCRIBER: ORIGIN_PRESCRIPTEUR,
        JobApplication.SENDER_KIND_SIAE_STAFF: ORIGIN_EMPLOYEUR,
    }

    if sender_kind in sender_kind_mapping.keys():
        return sender_kind_mapping[sender_kind]
    # The param has to be set, so we need to pick a default value
    return sender_kind_mapping[JobApplication.SENDER_KIND_JOB_SEEKER]


def _mise_a_jour_parameters(encrypted_identifier: str, job_application, pass_approved_code: str):
    """
    The necessary parameters to notify Pole Emploi that a Pass has been granted
    """
    siae = job_application.to_siae
    approval = job_application.approval

    if pass_approved_code == POLE_EMPLOI_PASS_REFUSED:
        # The necessary parameters to notify Pole Emploi of a refusal
        return {
            "idNational": encrypted_identifier,
            "statutReponsePassIAE": POLE_EMPLOI_PASS_REFUSED,
            "origineCandidature": _mise_a_jour_sender_kind_param(job_application.sender_kind),
        }
    # The necessary parameters to notify Pole Emploi that a Pass has been granted
    return {
        "idNational": encrypted_identifier,
        "statutReponsePassIAE": POLE_EMPLOI_PASS_APPROVED,
        "typeSIAE": _mise_a_jour_siae_kind_param(siae),
        "dateDebutPassIAE": approval.start_at.strftime(DATE_FORMAT),
        "dateFinPassIAE": approval.end_at.strftime(DATE_FORMAT),
        "numPassIAE": approval.number,
        "numSIRETsiae": siae.siret,
        "origineCandidature": _mise_a_jour_sender_kind_param(job_application.sender_kind),
    }
