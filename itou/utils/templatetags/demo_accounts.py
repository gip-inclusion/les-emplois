import logging

from django import template
from django.urls import reverse

from itou.users.enums import UserKind
from itou.users.models import User


logger = logging.getLogger(__name__)
register = template.Library()


@register.simple_tag
def employers_accounts_tag():
    action_url = reverse("login:employer")
    return [
        {
            "email": "test+etti@inclusion.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "etti.svg",
            "location": "Beaucaire (30)",
            "title": "Entreprise de Travail Temporaire d'Insertion (E.T.T.I)",
            "action_url": action_url,
        },
        {
            "email": "test+ei@inclusion.gouv.fr",
            "description": "2 postes ouverts au recrutement",
            "image": "ei.svg",
            "location": "St-Etienne du Grès (13)",
            "title": "Entreprise d'Insertion (E.I.)",
            "action_url": action_url,
        },
        {
            "email": "test+geiq@inclusion.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "geiq.svg",
            "location": "Tarascon (13)",
            "title": "Groupement d'Employeurs pour l'Insertion et la Qualification (G.E.I.Q.)",
            "action_url": action_url,
        },
        {
            "email": "test+ea@inclusion.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "ea.svg",
            "location": "Fontvieille (13)",
            "title": "Entreprise Adaptée (E.A.)",
            "action_url": action_url,
        },
        {
            "email": "test+ai@inclusion.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "ai.svg",
            "location": "Tours (37)",
            "title": "Association intermédiaire (A.I.)",
            "action_url": action_url,
        },
    ]


@register.simple_tag
def prescribers_accounts_tag():
    action_url = reverse("login:prescriber")
    return [
        {
            "title": "Prescripteur habilité",
            "email": "test+prescripteur@inclusion.gouv.fr",
            "image": "prescripteur_habilite.svg",
            "action_url": action_url,
        },
        {
            "title": "Orienteur <br>(prescripteur non habilité)",
            "email": "test+orienteur@inclusion.gouv.fr",
            "image": "prescripteur_non_habilite.svg",
            "action_url": action_url,
        },
        {
            "title": "Orienteur seul,<br> sans organisation",
            "email": "test+orienteur-solo@inclusion.gouv.fr",
            "image": "prescripteur_solo.svg",
            "action_url": action_url,
        },
    ]


@register.simple_tag
def job_seekers_accounts_tag():
    user_email = "test+de@inclusion.gouv.fr"
    try:
        user_public_id = User.objects.get(kind=UserKind.JOB_SEEKER, email=user_email).public_id
    except User.DoesNotExist:
        logger.warning(
            f"Unable to initialise job_seekers_accounts_tag: no job seeker with email='{user_email}' found !"
        )
        return []  # Fail.

    action_url = reverse("login:existing_user", kwargs={"user_public_id": user_public_id})
    return [{"email": user_email, "image": "de.svg", "action_url": action_url}]
