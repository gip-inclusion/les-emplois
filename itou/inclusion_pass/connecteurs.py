"""Data sources of the pass. Each connector returns the value to store, as a dict.

Calls are simulated: values are deterministic for each person, and the demo persona gets the values of the
mockup. The RSA status is fetched for real from API Particulier when a token is configured and the person's
identity is complete.
"""

import datetime
import hashlib
import logging

from django.conf import settings
from django.utils import formats, timezone

from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.inclusion_pass import catalogue
from itou.users.enums import Title
from itou.utils.apis import api_particulier


logger = logging.getLogger(__name__)

PERSONA_EMAIL = "persona.pass@example.com"


def _tirage(personne, cle, probabilite):
    """Deterministic pseudo-random draw, so that a person always gets the same simulated values."""
    if personne.email == PERSONA_EMAIL:
        return None
    empreinte = hashlib.sha256(f"{personne.email}:{cle}".encode()).digest()
    return empreinte[0] / 256 < probabilite


def _feminin(personne, masculin, feminin):
    return feminin if personne.title == Title.MME else masculin


def identite(personne):
    profile = personne.jobseeker_profile
    return {
        "prenom": personne.first_name,
        "nom": personne.last_name.upper(),
        "date_naissance": profile.birthdate.isoformat() if profile.birthdate else "",
        "adresse": ", ".join(
            part for part in (personne.address_line_1, f"{personne.post_code} {personne.city}".strip()) if part
        ),
    }


def email(personne):
    return {"texte": personne.email}


def telephone(personne):
    return {"texte": personne.phone or "06 12 34 56 78"}


def statut_rsa(personne):
    if settings.API_PARTICULIER_TOKEN and api_particulier.has_required_info(personne):
        try:
            with api_particulier.client() as client:
                response = api_particulier._request(
                    client, api_particulier.ENDPOINTS[AdministrativeCriteriaKind.RSA], personne
                )
            data = response["data"]
            return {"beneficiaire": data["est_beneficiaire"], "depuis": data.get("date_debut_droit") or ""}
        except Exception:
            logger.exception("Appel API Particulier RSA en échec, repli sur la valeur simulée")
    beneficiaire = _tirage(personne, catalogue.STATUT_RSA, 0.6)
    return {"beneficiaire": beneficiaire is not False, "depuis": "2025-05-01"}


def aah(personne):
    return {"beneficiaire": bool(_tirage(personne, catalogue.AAH, 0.1))}


def ass(personne):
    return {"beneficiaire": bool(_tirage(personne, catalogue.ASS, 0.2))}


def statut_emploi(personne):
    return {"texte": "Sans emploi depuis 18 mois"}


def statut_demandeur_emploi(personne):
    inscrit = _tirage(personne, catalogue.STATUT_DEMANDEUR_EMPLOI, 0.8)
    return {"inscrit": inscrit is not False, "categorie": "catégorie 1", "depuis": "2024-12-01"}


def rqth(personne):
    reconnue = _tirage(personne, catalogue.RQTH, 0.15)
    return {"reconnue": reconnue is not False, "fin": "2028-06-30"}


def pass_iae(personne):
    approval = personne.approvals.order_by("-end_at").first()
    if approval is None or approval.end_at < timezone.localdate():
        return {"en_cours": False}
    return {"en_cours": True, "numero": approval.number, "fin": approval.end_at.isoformat()}


def mobilite(personne):
    return {"texte": "Pas de permis de conduire, dépend des transports en commun"}


def garde_enfants(personne):
    return {"texte": "Un enfant de moins de 3 ans, sans solution de garde"}


def numerique(personne):
    return {"texte": "Autonomie partielle sur les démarches en ligne"}


def _piece(cle):
    def connecteur(personne):
        return {"nom": catalogue.libelle(cle)}

    return connecteur


def en_qpv(personne):
    """Whether the person lives in a priority neighbourhood (QPV). Simulated, used for the impact report only."""
    return _tirage(personne, "qpv", 0.3) is not False


CONNECTEURS = {
    catalogue.IDENTITE: identite,
    catalogue.EMAIL: email,
    catalogue.TELEPHONE: telephone,
    catalogue.STATUT_RSA: statut_rsa,
    catalogue.AAH: aah,
    catalogue.ASS: ass,
    catalogue.STATUT_EMPLOI: statut_emploi,
    catalogue.STATUT_DEMANDEUR_EMPLOI: statut_demandeur_emploi,
    catalogue.RQTH: rqth,
    catalogue.PASS_IAE: pass_iae,
    catalogue.MOBILITE: mobilite,
    catalogue.GARDE_ENFANTS: garde_enfants,
    catalogue.NUMERIQUE: numerique,
    catalogue.CV: _piece(catalogue.CV),
    catalogue.JUSTIFICATIF_DOMICILE: _piece(catalogue.JUSTIFICATIF_DOMICILE),
    catalogue.AVIS_FISCAL: _piece(catalogue.AVIS_FISCAL),
}


def lignes(cle, valeur, personne):
    """Human-readable lines of a stored value: [(label, text), …]. Most data have a single line."""
    info = catalogue.DONNEES[cle]
    if cle == catalogue.IDENTITE:
        textes = {**valeur, "date_naissance": _date(valeur.get("date_naissance"), "d/m/Y")}
        return [(libelle, textes.get(champ) or "-") for champ, libelle in info["lignes"].items()]
    return [(info["libelle"], resume(cle, valeur, personne))]


def resume(cle, valeur, personne):
    """One-line human summary of a stored value, used in templates and the CSV export."""
    if "texte" in valeur:
        return valeur["texte"]
    if "nom" in valeur:
        return valeur["nom"]
    if cle == catalogue.STATUT_RSA:
        if not valeur.get("beneficiaire"):
            return "Non bénéficiaire"
        return f"Bénéficiaire du RSA depuis {_date(valeur.get('depuis'), 'F Y')}"
    if cle in (catalogue.AAH, catalogue.ASS):
        return "Bénéficiaire" if valeur.get("beneficiaire") else "Non bénéficiaire"
    if cle == catalogue.STATUT_DEMANDEUR_EMPLOI:
        if not valeur.get("inscrit"):
            return _feminin(personne, "Non inscrit", "Non inscrite")
        inscrit = _feminin(personne, "Inscrit", "Inscrite")
        return f"{inscrit}, {valeur.get('categorie', '')}, depuis {_date(valeur.get('depuis'), 'F Y')}"
    if cle == catalogue.RQTH:
        if not valeur.get("reconnue"):
            return "Non reconnue"
        return f"Reconnue, valable jusqu’au {_date(valeur.get('fin'), 'd/m/Y')}"
    if cle == catalogue.PASS_IAE:
        if not valeur.get("en_cours"):
            return "Aucun PASS\u00a0IAE en cours"
        return f"PASS\u00a0IAE n°\u00a0{valeur['numero']}, valable jusqu’au {_date(valeur['fin'], 'd/m/Y')}"
    return str(valeur)


def _date(iso, fmt):
    if not iso:
        return "?"
    return formats.date_format(datetime.date.fromisoformat(iso), fmt)
