"""Mock data used by the SPS views as we cannot access France Travail API yet."""

HARDCODED_DIAGNOSIS = [
    {
        "section": "Contraintes",
        "items": [
            {
                "title": "Surmonter ses contraintes familiales",
                "badges": [
                    {"label": "Prioritaire", "css": "bg-danger-lighter text-danger"},
                    {"label": "Impact fort", "css": "bg-warning-lighter text-warning"},
                ],
                "bullets": [
                    "Faire un point complet sur sa mobilité",
                    "Aucun moyen de transport à disposition",
                ],
                "footer": "Exploré le 18/04/2025 par Céline PRADEL — APE MONTAUBAN ALBASUD",
            },
            {
                "title": "Faire face à des difficultés financières",
                "badges": [],
                "bullets": [
                    "Sans aucune ressource",
                    "Mobiliser un dispositif d’aide alimentaire",
                ],
                "footer": "Exploré le 18/04/2025 par Céline PRADEL — APE MONTAUBAN ALBASUD",
            },
        ],
    },
    {
        "section": "Autonomie numérique",
        "items": [
            {
                "title": "Identifier ses points forts et ses compétences",
                "badges": [{"label": "Besoin", "css": "bg-warning-lighter text-warning"}],
                "bullets": [],
                "footer": "Exploré le 18/04/2025 par Céline PRADEL — APE MONTAUBAN ALBASUD",
            },
            {
                "title": "Surmonter ses contraintes familiales",
                "badges": [],
                "bullets": ["Faire un point complet sur sa mobilité"],
                "footer": "Exploré le 18/04/2025 par Céline PRADEL — APE MONTAUBAN ALBASUD",
            },
        ],
    },
    {
        "section": "Pouvoir d’agir",
        "items": [
            {
                "title": "Possible perte de confiance",
                "badges": [],
                "bullets": [],
                "footer": "Exploré le 18/04/2025 par Céline PRADEL — APE MONTAUBAN ALBASUD",
            },
        ],
    },
    {
        "section": "Projet professionnel",
        "items": [
            {
                "title": "Exploitant / Exploitante agricole",
                "badges": [{"label": "Point fort", "css": "bg-success-lighter text-success"}],
                "bullets": [],
                "footer": "Exploré le 18/04/2025 par Céline PRADEL — APE MONTAUBAN ALBASUD",
            },
        ],
    },
]


_SIAE_MORE_JOBS = [
    {"label": "Agent / Agente d’entretien des espaces verts", "city": "Le Bouscat - 33"},
    {"label": "Manutentionnaire", "city": "Le Bouscat - 33", "candidates_badge": "20+ candidatures"},
    {"label": "Cariste", "city": "Le Bouscat - 33"},
    {"label": "Préparateur / Préparatrice de commandes", "city": "Le Bouscat - 33"},
    {"label": "Agent / Agente de propreté", "city": "Le Bouscat - 33"},
    {"label": "Aide-cuisinier / Aide-cuisinière", "city": "Le Bouscat - 33"},
    {"label": "Magasinier / Magasinière", "city": "Le Bouscat - 33"},
]


HARDCODED_RECOMMENDATIONS = [
    {
        "kind_label": "PLIE",
        "rationale": "RSA, QPV, niveau d’études inférieur au niveau V",
        "providers": [
            {
                "kind_short": "Plan Local pour l’Insertion et l’Emploi (PLIE)",
                "name": "Lille Avenirs",
                "distance_km": "2,7",
                "address": "513 Rue Sans Souci, 69760 Limonest",
                "description": (
                    "Le Plan Local pour l’Insertion et l’Emploi a pour mission de favoriser "
                    "le retour à l’emploi durable ou l’accès à une formation qualifiante "
                    "pour les personnes rencontrant des difficultés dans leur insertion "
                    "socio-professionnelle."
                ),
                "show_map": True,
                "lat": 45.8326,
                "lon": 4.7719,
                "jobs": [],
                "pk": "77739d9b-2fe3-4a41-a57d-d8e0ebc44ff8",
            },
        ],
    },
    {
        "kind_label": "Groupement d’Employeurs pour l’Insertion et la Qualification (GEIQ)",
        "rationale": "RSA, QPV, projet professionnel : Exploitant / Exploitante agricole",
        "providers": [
            {
                "kind_short": "ETTI - Entreprise de Travail Temporaire d’Insertion",
                "name": "Une nouvelle chance",
                "subtitle": "(Régie De Quartier Tremblay)",
                "distance_km": "2,7",
                "address": "513 Rue Sans Souci, 69760 Limonest",
                "show_map": False,
                "lat": 45.8201,
                "lon": 4.7853,
                "jobs": [
                    {"label": "Exploitant / Exploitante agricole", "city": "Le Bouscat - 33"},
                ],
                "pk": "7ec31a7b-e52f-4bb0-ac95-5739bdc9d1c1",
            },
        ],
    },
    {
        "kind_label": "emplois d’insertion (SIAE)",
        "rationale": "RSA",
        "providers": [
            {
                "kind_short": "ETTI - Entreprise de Travail Temporaire d’Insertion",
                "name": "Une nouvelle chance",
                "subtitle": "(Régie De Quartier Tremblay)",
                "distance_km": "2,7",
                "address": "513 Rue Sans Souci, 69760 Limonest",
                "show_map": True,
                "jobs": [
                    {"label": "Aide maçon/maçonne Voirie et réseaux divers", "city": "Le Bouscat - 33"},
                    {
                        "label": "Aide peintre",
                        "city": "Le Bouscat - 33",
                        "candidates_badge": "20+ candidatures",
                    },
                    {"label": "Aide plombier / plombière", "city": "Le Bouscat - 33"},
                    *_SIAE_MORE_JOBS,
                ],
                "lat": 45.8410,
                "lon": 4.7601,
                "pk": "820a949d-7c81-4250-921c-87b1255510b1",
            },
            {
                "kind_short": "ETTI - Entreprise de Travail Temporaire d’Insertion",
                "name": "Une nouvelle chance",
                "subtitle": "(Régie De Quartier Tremblay)",
                "distance_km": "2,7",
                "address": "513 Rue Sans Souci, 69760 Limonest",
                "show_map": True,
                "jobs": [
                    {"label": "Aide maçon/maçonne Voirie et réseaux divers", "city": "Le Bouscat - 33"},
                    {
                        "label": "Aide peintre",
                        "city": "Le Bouscat - 33",
                        "candidates_badge": "20+ candidatures",
                    },
                    {"label": "Aide plombier / plombière", "city": "Le Bouscat - 33"},
                    *_SIAE_MORE_JOBS,
                ],
                "lat": 45.8152,
                "lon": 4.7902,
                "pk": "a72e4c09-3fd4-45c0-8477-bb85f17c5da9",
            },
        ],
    },
]
