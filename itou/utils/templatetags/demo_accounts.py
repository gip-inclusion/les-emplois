from django import template


register = template.Library()


@register.simple_tag
def employers_accounts_tag():
    return [
        {
            "title": "Entreprise de Travail Temporaire d'Insertion (E.T.T.I)",
            "email": "test+etti@inclusion.beta.gouv.fr",
            "image": "etti.svg",
        },
        {"title": "Entreprise d'Insertion (E.I.)", "email": "test+ei@inclusion.beta.gouv.fr", "image": "ei.svg"},
        {
            "title": "Groupement d'Employeurs pour l'Insertion et la Qualification (G.E.I.Q.)",
            "email": "test+geiq@inclusion.beta.gouv.fr",
            "image": "geiq.svg",
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
            "title": "Prescripteur non habilité",
            "email": "test+orienteur@inclusion.beta.gouv.fr",
            "image": "prescripteur_non_habilite.svg",
        },
        {
            "title": "Prescripteur seul, sans organisation",
            "email": "test+orienteur-solo@inclusion.beta.gouv.fr",
            "image": "prescripteur_solo.svg",
        },
    ]


@register.simple_tag
def job_seekers_accounts_tag():
    return [{"title": "Candidat", "email": "test+de@inclusion.beta.gouv.fr", "image": "de.svg"}]
