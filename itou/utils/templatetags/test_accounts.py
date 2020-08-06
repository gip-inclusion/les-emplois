from django import template


register = template.Library()


@register.simple_tag
def employers_accounts_tag():
    return [
        {
            "email": "test+etti@inclusion.beta.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "etti.svg",
            "location": "Beaucaire (30)",
            "title": "Entreprise de Travail Temporaire d'Insertion (E.T.T.I)",
        },
        {
            "email": "test+ei@inclusion.beta.gouv.fr",
            "description": "2 postes ouverts au recrutement",
            "image": "ei.svg",
            "location": "St-Etienne du Grès (13)",
            "title": "Entreprise d'Insertion (E.I.)",
        },
        {
            "email": "test+geiq@inclusion.beta.gouv.fr",
            "description": "1 poste ouvert au recrutement",
            "image": "geiq.svg",
            "location": "Tarascon (13)",
            "title": "Groupement d'Employeurs pour l'Insertion et la Qualification (G.E.I.Q.)",
        },
    ]


@register.simple_tag
def prescribers_accounts_tag():
    return [
        {
            "title": "Prescripteur habilité",
            "email": "test+prescripteur@inclusion.beta.gouv.fr",
            "image": "prescripteur_habilite.svg",
        },
        {
            "title": "Orienteur <br>(prescripteur non habilité)",
            "email": "test+orienteur@inclusion.beta.gouv.fr",
            "image": "prescripteur_non_habilite.svg",
        },
        {
            "title": "Orienteur seul,<br> sans organisation",
            "email": "test+orienteur-solo@inclusion.beta.gouv.fr",
            "image": "prescripteur_solo.svg",
        },
    ]


@register.simple_tag
def job_seekers_accounts_tag():
    return [{"email": "test+de@inclusion.beta.gouv.fr", "image": "de.svg"}]
