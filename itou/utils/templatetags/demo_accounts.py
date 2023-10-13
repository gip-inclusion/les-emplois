from django import template
from django.urls import reverse


register = template.Library()


@register.simple_tag
def employers_accounts_tag():
    action_url = reverse("login:employer")
    return [
        {
            "email": "test+etti@inclusion.beta.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "etti.svg",
            "location": "Beaucaire (30)",
            "title": "Entreprise de Travail Temporaire d'Insertion (E.T.T.I)",
            "action_url": action_url,
        },
        {
            "email": "test+ei@inclusion.beta.gouv.fr",
            "description": "2 postes ouverts au recrutement",
            "image": "ei.svg",
            "location": "St-Etienne du Grès (13)",
            "title": "Entreprise d'Insertion (E.I.)",
            "action_url": action_url,
        },
        {
            "email": "test+geiq@inclusion.beta.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "geiq.svg",
            "location": "Tarascon (13)",
            "title": "Groupement d'Employeurs pour l'Insertion et la Qualification (G.E.I.Q.)",
            "action_url": action_url,
        },
        {
            "email": "test+ea@inclusion.beta.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "ea.svg",
            "location": "Fontvieille (13)",
            "title": "Entreprise Adaptée (E.A.)",
            "action_url": action_url,
        },
        {
            "email": "test+ai@inclusion.beta.gouv.fr",
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
            "email": "test+prescripteur@inclusion.beta.gouv.fr",
            "image": "prescripteur_habilite.svg",
            "action_url": action_url,
        },
        {
            "title": "Orienteur <br>(prescripteur non habilité)",
            "email": "test+orienteur@inclusion.beta.gouv.fr",
            "image": "prescripteur_non_habilite.svg",
            "action_url": action_url,
        },
        {
            "title": "Orienteur seul,<br> sans organisation",
            "email": "test+orienteur-solo@inclusion.beta.gouv.fr",
            "image": "prescripteur_solo.svg",
            "action_url": action_url,
        },
    ]


@register.simple_tag
def job_seekers_accounts_tag():
    action_url = reverse("login:job_seeker")
    return [{"email": "test+de@inclusion.beta.gouv.fr", "image": "de.svg", "action_url": action_url}]
