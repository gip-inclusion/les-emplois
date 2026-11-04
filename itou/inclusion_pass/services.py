"""Single entry point to consents and shared data: views must not read them directly."""

import random

from django.db.models import Avg, F, OuterRef, Subquery
from django.utils import timezone

from itou.inclusion_pass import catalogue, connecteurs
from itou.inclusion_pass.models import (
    AccesDonnee,
    Accompagnement,
    Consentement,
    DonneePartagee,
    NotificationPrescripteur,
    SituationSuivi,
)
from itou.insertion.enums import OrientationStatus
from itou.insertion.models import Orientation
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import Title


Action = AccesDonnee.Action
DEMO_PRESCRIPTEUR_EMAIL = "demo.emplois+prescripteur@inclusion.gouv.fr"


def _journal(personne, offreur, cle, action, source=""):
    AccesDonnee.objects.create(personne=personne, offreur=offreur, donnee=cle, action=action, source=source)


def cles_consenties(personne, offreur):
    return set(
        Consentement.objects.actifs().filter(personne=personne, offreur=offreur).values_list("donnee", flat=True)
    )


def accorder(personne, offreur, cles):
    """Record the person's consent for each key, start the follow-up and fetch the data.

    Keys not requested by the offreur (nor in the authorizations catalogue) are ignored. A pending orientation
    towards the offreur is accepted: activating the pass means the follow-up starts.
    """
    autorisees = set(offreur.donnees_demandees) | set(catalogue.AUTORISATIONS)
    nouvelles = set(cles) & autorisees - cles_consenties(personne, offreur)
    for cle in nouvelles:
        Consentement.objects.create(personne=personne, offreur=offreur, donnee=cle)
        _journal(personne, offreur, cle, Action.OCTROI)

    orientation = orientation_recue(personne, offreur)
    if orientation and orientation.accept.is_available():
        orientation.accept()
    accompagnement, created = Accompagnement.objects.get_or_create(
        personne=personne,
        offreur=offreur,
        ended_at=None,
        defaults={"orientation": orientation, "prescripteur": trouver_prescripteur(personne, orientation)},
    )
    recuperer(personne, offreur)
    if created:
        # Entry statuses come from the sources directly: they feed the anonymous impact report only
        accompagnement.statuts_entree = {
            catalogue.STATUT_RSA: connecteurs.statut_rsa(personne)["beneficiaire"],
            catalogue.STATUT_DEMANDEUR_EMPLOI: connecteurs.statut_demandeur_emploi(personne)["inscrit"],
            "qpv": connecteurs.en_qpv(personne),
        }
        accompagnement.save(update_fields=["statuts_entree"])
    # The reception QR code can be scanned again: the authorization may come on a later visit
    if catalogue.INFORMER_PRESCRIPTEUR in cles_consenties(personne, offreur) and (
        created or catalogue.INFORMER_PRESCRIPTEUR in nouvelles
    ):
        notifier_prescripteur(accompagnement)
    return accompagnement


def retirer(personne, offreur, cle=None):
    """Revoke one consent, or all consents given to the offreur when no key is given."""
    consentements = Consentement.objects.actifs().filter(personne=personne, offreur=offreur)
    if cle:
        consentements = consentements.filter(donnee=cle)
    for consentement in consentements:
        consentement.revoked_at = timezone.now()
        consentement.save(update_fields=["revoked_at"])
        _journal(personne, offreur, consentement.donnee, Action.RETRAIT)


def recuperer(personne, offreur):
    """Fetch every consented data from its source and keep a dated copy."""
    for cle in cles_consenties(personne, offreur) & set(connecteurs.CONNECTEURS):
        try:
            valeur = connecteurs.CONNECTEURS[cle](personne)
        except Exception:
            DonneePartagee.objects.filter(personne=personne, donnee=cle).update(erreur="Source indisponible")
            continue
        DonneePartagee.objects.update_or_create(
            personne=personne,
            donnee=cle,
            defaults={
                "valeur": valeur,
                "source": catalogue.DONNEES[cle]["source"],
                "fetched_at": timezone.now(),
                "erreur": "",
            },
        )
        _journal(personne, offreur, cle, Action.RECUPERATION, source=catalogue.source(cle)["libelle"])


def donnees_pour_offreur(offreur, personne, journaliser=True):
    """Return the person's record as seen by the offreur, grouped by block.

    Each line is filled only when the consent is active, otherwise it says the data is not shared or
    that the access was withdrawn.

    Returns:
        A list of blocks ``{"cle", "libelle", "icone", "lignes"}``, in catalogue order.
    """
    consentements = {c.donnee: c for c in Consentement.objects.filter(personne=personne, offreur=offreur)}
    donnees = {d.donnee: d for d in DonneePartagee.objects.filter(personne=personne)}
    blocs = []
    for bloc_cle, bloc, cles in catalogue.par_bloc(offreur.donnees_demandees):
        lignes = []
        for cle, info in cles:
            base = {"cle": cle, "source": catalogue.source(cle), "statut": "non_partagee"}
            consentement = consentements.get(cle)
            donnee = donnees.get(cle)
            if consentement and consentement.revoked_at:
                base.update(statut="retiree", retiree_le=consentement.revoked_at)
            elif consentement and donnee:
                base.update(statut="partagee", fetched_at=donnee.fetched_at, erreur=donnee.erreur)
                if journaliser:
                    _journal(personne, offreur, cle, Action.CONSULTATION, source=base["source"]["libelle"])
            if base["statut"] == "partagee":
                textes = connecteurs.lignes(cle, donnee.valeur, personne)
            else:
                textes = [(libelle, None) for libelle in info.get("lignes", {cle: info["libelle"]}).values()]
            lignes += [{**base, "libelle": libelle, "texte": texte} for libelle, texte in textes]
        blocs.append({"cle": bloc_cle, **bloc, "lignes": lignes})
    return blocs


def orientation_recue(personne, offreur):
    """The most recent orientation of the person towards one of the offreur services, if any.

    An orientation that already led to an ended follow-up does not count for a new one.
    """
    deja_suivies = (
        Accompagnement.objects.filter(personne=personne, offreur=offreur)
        .exclude(ended_at=None)
        .exclude(orientation=None)
        .values("orientation")
    )
    return (
        Orientation.objects.filter(beneficiary=personne, service__structure=offreur.structure)
        .exclude(status__in=[OrientationStatus.REFUSED, OrientationStatus.EXPIRED])
        .exclude(pk__in=deja_suivies)
        .select_related("sender_prescriber_organization")
        .order_by("-created_at")
        .first()
    )


def trouver_prescripteur(personne, orientation=None):
    """Find who oriented the person: the sender of the orientation, or the last prescriber of a job application."""
    if orientation and orientation.sender_prescriber_organization:
        return orientation.sender_prescriber_organization
    candidature = (
        personne.job_applications.exclude(sender_prescriber_organization=None)
        .select_related("sender_prescriber_organization")
        .order_by("-created_at")
        .first()
    )
    return candidature.sender_prescriber_organization if candidature else None


def prescripteur_de_demo():
    """Organization of the demo prescriber account, which sends the orientations of the demo data."""
    membership = (
        PrescriberMembership.objects.filter(user__email=DEMO_PRESCRIPTEUR_EMAIL)
        .select_related("organization")
        .order_by("joined_at")
        .first()
    )
    return membership.organization if membership else None


def notifier_prescripteur(accompagnement):
    """Notify the prescriber who sent the orientation, shown in its list of sent orientations until opened.

    Without an orientation sent by a prescriber, there is nowhere to show the notification: nothing is sent.
    """
    orientation = accompagnement.orientation
    if orientation is None or orientation.sender_prescriber_organization_id is None:
        return
    prescripteur = orientation.sender_prescriber_organization
    personne = accompagnement.personne
    message = f"Pass inclusion activé le {timezone.localdate(accompagnement.started_at):%d/%m/%Y}"
    NotificationPrescripteur.objects.create(prescripteur=prescripteur, accompagnement=accompagnement, message=message)
    _journal(
        personne,
        accompagnement.offreur,
        catalogue.INFORMER_PRESCRIPTEUR,
        Action.NOTIFICATION,
        prescripteur.display_name,
    )


def _notifications_non_lues(organisation):
    return NotificationPrescripteur.objects.filter(prescripteur=organisation, lue_le=None)


def avec_notifications(orientations):
    """Annotate each orientation with ``pass_notification``, the message of its oldest unread notification."""
    notifications = NotificationPrescripteur.objects.filter(
        prescripteur=OuterRef("sender_prescriber_organization"),
        accompagnement__orientation=OuterRef("pk"),
        lue_le=None,
    ).order_by("created_at")
    return orientations.annotate(pass_notification=Subquery(notifications.values("message")[:1]))


def nombre_notifications_non_lues(organisation):
    return _notifications_non_lues(organisation).count()


def marquer_notifications_lues(orientation, organisation):
    _notifications_non_lues(organisation).filter(accompagnement__orientation=orientation).update(lue_le=timezone.now())


def envoyer_bilan(bilan):
    """Save the report of the follow-up, which ends it."""
    bilan.save()
    accompagnement = bilan.accompagnement
    if accompagnement.ended_at is None:
        accompagnement.ended_at = timezone.now()
        accompagnement.save(update_fields=["ended_at"])


def simuler_suivi(accompagnement, rng=random):
    """Fast-forward 12 months: end the follow-up and create the 3, 6 and 12 month situations."""
    Situation = SituationSuivi.Situation
    if accompagnement.ended_at is None:
        accompagnement.ended_at = timezone.now()
        accompagnement.save(update_fields=["ended_at"])
    accompagnement.situations.all().delete()
    parcours = rng.choice(
        [
            [Situation.RECHERCHE, Situation.FORMATION, Situation.EMPLOI],
            [Situation.FORMATION, Situation.EMPLOI, Situation.EMPLOI],
            [Situation.EMPLOI, Situation.EMPLOI, Situation.EMPLOI],
            [Situation.RECHERCHE, Situation.RECHERCHE, Situation.EMPLOI],
            [Situation.RECHERCHE, Situation.RECHERCHE, Situation.RECHERCHE],
        ]
    )
    for mois, situation in zip((3, 6, 12), parcours):
        SituationSuivi.objects.create(accompagnement=accompagnement, mois=mois, situation=situation)


def _tranche_age(accompagnement):
    birthdate = accompagnement.personne.jobseeker_profile.birthdate
    if birthdate is None:
        return "Non renseigné"
    debut = timezone.localdate(accompagnement.started_at)
    age = debut.year - birthdate.year - ((debut.month, debut.day) < (birthdate.month, birthdate.day))
    if age < 26:
        return "Moins de 26 ans"
    if age < 45:
        return "26 à 44 ans"
    return "45 ans et plus"


def _repartition(accompagnements, categorie, ordre):
    comptes = dict.fromkeys(ordre, 0)
    for accompagnement in accompagnements:
        comptes[categorie(accompagnement)] += 1
    return [{"libelle": libelle, "nombre": nombre} for libelle, nombre in comptes.items() if nombre]


def bilan_impact(offreur, accompagnements=None):
    """Anonymous impact report of the offreur: activity, entry profile and positive exits at 3, 6 and 12 months.

    Args:
        offreur: The offreur whose follow-ups are counted.
        accompagnements: A subset of the offreur follow-ups (queryset), all of them by default.
    """
    queryset = offreur.accompagnements.all() if accompagnements is None else accompagnements
    duree = queryset.exclude(ended_at=None).aggregate(d=Avg(F("ended_at") - F("started_at")))["d"]
    accompagnements = list(queryset.select_related("personne__jobseeker_profile").prefetch_related("situations"))
    termines = [a for a in accompagnements if a.ended_at]
    sorties = {}
    for mois in (3, 6, 12):
        situations = [s for a in termines for s in a.situations.all() if s.mois == mois]
        positives = sum(s.est_positive for s in situations)
        sorties[mois] = {
            "suivis": len(situations),
            "positives": positives,
            "taux": round(100 * positives / len(situations)) if situations else None,
        }
    genres = {Title.MME: "Femmes", Title.M: "Hommes"}
    return {
        "total": len(accompagnements),
        "en_cours": len(accompagnements) - len(termines),
        "termines": len(termines),
        "duree_moyenne_jours": duree.days if duree else None,
        "sorties": sorties,
        "rsa": sum(bool(a.statuts_entree.get(catalogue.STATUT_RSA)) for a in accompagnements),
        "demandeurs_emploi": sum(
            bool(a.statuts_entree.get(catalogue.STATUT_DEMANDEUR_EMPLOI)) for a in accompagnements
        ),
        "repartitions": {
            "qpv": _repartition(
                accompagnements,
                lambda a: "Résident QPV" if a.statuts_entree.get("qpv") else "Hors QPV",
                ["Résident QPV", "Hors QPV"],
            ),
            "rsa": _repartition(
                accompagnements,
                lambda a: "Bénéficiaire du RSA" if a.statuts_entree.get(catalogue.STATUT_RSA) else "Non bénéficiaire",
                ["Bénéficiaire du RSA", "Non bénéficiaire"],
            ),
            "genre": _repartition(
                accompagnements,
                lambda a: genres.get(a.personne.title, "Non renseigné"),
                ["Femmes", "Hommes", "Non renseigné"],
            ),
            "age": _repartition(
                accompagnements, _tranche_age, ["Moins de 26 ans", "26 à 44 ans", "45 ans et plus", "Non renseigné"]
            ),
        },
    }


MODELES_EXPORT = {
    "fse": "Reporting FSE",
    "cd": "Financement du conseil départemental",
    "complet": "Bilan complet",
}


def _taux(sortie):
    return "" if sortie["taux"] is None else f"{sortie['taux']}\xa0%"


def _nombres(repartition):
    return {serie["libelle"]: serie["nombre"] for serie in repartition}


def _lignes_complet(bilan):
    lignes = [
        ["Personnes accompagnées", bilan["total"]],
        ["Accompagnements en cours", bilan["en_cours"]],
        ["Accompagnements terminés", bilan["termines"]],
        ["Durée moyenne (jours)", bilan["duree_moyenne_jours"] or ""],
        ["Bénéficiaires du RSA à l’entrée", bilan["rsa"]],
        ["Demandeurs d’emploi à l’entrée", bilan["demandeurs_emploi"]],
    ]
    lignes += [[f"Sorties positives à {mois} mois", _taux(sortie)] for mois, sortie in bilan["sorties"].items()]
    for repartition in bilan["repartitions"].values():
        lignes += [[serie["libelle"], serie["nombre"]] for serie in repartition]
    return lignes


def _lignes_fse(bilan):
    # Participant indicators of the FSE+ reporting: entry profile, then situation after the follow-up
    genres = _nombres(bilan["repartitions"]["genre"])
    ages = _nombres(bilan["repartitions"]["age"])
    return [
        ["Participants", bilan["total"]],
        *[[genre, genres.get(genre, 0)] for genre in ("Femmes", "Hommes")],
        *[[age, ages.get(age, 0)] for age in ("Moins de 26 ans", "26 à 44 ans", "45 ans et plus")],
        ["Demandeurs d’emploi à l’entrée", bilan["demandeurs_emploi"]],
        ["Bénéficiaires de minima sociaux (RSA) à l’entrée", bilan["rsa"]],
        ["Résidents QPV", _nombres(bilan["repartitions"]["qpv"]).get("Résident QPV", 0)],
        ["Participants sortis", bilan["termines"]],
        *[[f"En emploi ou en formation à {mois} mois", _taux(bilan["sorties"][mois])] for mois in (3, 6)],
    ]


def _lignes_cd(bilan):
    # The department funds the follow-up of RSA beneficiaries: the report only counts them
    return [
        ["Bénéficiaires du RSA accompagnés", bilan["total"]],
        ["Accompagnements en cours", bilan["en_cours"]],
        ["Accompagnements terminés", bilan["termines"]],
        ["Durée moyenne (jours)", bilan["duree_moyenne_jours"] or ""],
        *[[f"Sorties positives à {mois} mois", _taux(sortie)] for mois, sortie in bilan["sorties"].items()],
        ["Résidents QPV", _nombres(bilan["repartitions"]["qpv"]).get("Résident QPV", 0)],
    ]


def lignes_export(offreur, modele):
    """Rows of the impact report export, in the format expected by a funder.

    Args:
        offreur: The offreur exporting its report.
        modele: A key of ``MODELES_EXPORT``.

    Returns:
        A list of ``[indicator, value]`` rows, preceded by the structure, the format and the date.
    """
    if modele == "cd":
        rsa = offreur.accompagnements.filter(**{f"statuts_entree__{catalogue.STATUT_RSA}": True})
        lignes = _lignes_cd(bilan_impact(offreur, rsa))
    else:
        lignes = {"fse": _lignes_fse, "complet": _lignes_complet}[modele](bilan_impact(offreur))
    return [
        ["Structure", offreur.display_name],
        ["Modèle", MODELES_EXPORT[modele]],
        ["Date d’export", f"{timezone.localdate():%d/%m/%Y}"],
        ["Indicateur", "Valeur"],
        *lignes,
    ]
