IDENTITE = "identite"
EMAIL = "email"
TELEPHONE = "telephone"
STATUT_RSA = "statut_rsa"
AAH = "aah"
ASS = "ass"
STATUT_EMPLOI = "statut_emploi"
STATUT_DEMANDEUR_EMPLOI = "statut_demandeur_emploi"
RQTH = "rqth"
PASS_IAE = "pass_iae"
MOBILITE = "mobilite"
GARDE_ENFANTS = "garde_enfants"
NUMERIQUE = "numerique"
CV = "cv"
JUSTIFICATIF_DOMICILE = "justificatif_domicile"
AVIS_FISCAL = "avis_fiscal"
INFORMER_PRESCRIPTEUR = "informer_prescripteur"
SUIVI_LONG = "suivi_long"

# Where the data comes from, with the badge shown next to each value
SOURCES = {
    "franceconnect": {
        "libelle": "FranceConnect",
        "icone": "ri-shield-user-line",
        "badge": "bg-info-lighter text-primary",
    },
    "france_travail": {
        "libelle": "France Travail",
        "icone": "ri-briefcase-4-line",
        "badge": "bg-accent-01-lighter text-primary",
    },
    "mdph": {
        "libelle": "MDPH, via France Travail",
        "icone": "ri-wheelchair-line",
        "badge": "bg-accent-01-lighter text-primary",
    },
    "caf": {"libelle": "CAF", "icone": "ri-hand-coin-line", "badge": "bg-warning-lighter text-primary"},
    "plateforme": {
        "libelle": "Plateforme de l’inclusion",
        "icone": "ri-community-line",
        "badge": "bg-accent-03-lighter text-primary",
    },
    "usager": {
        "libelle": "Envoyé par l’usager",
        "icone": "ri-user-shared-line",
        "badge": "bg-success-lighter text-primary",
    },
}

# Blocks of the person's record, in display order. Attachments are displayed in the side column.
BLOCS = {
    "identification": {"libelle": "Identification", "icone": "ri-user-line"},
    "contact": {"libelle": "Contact", "icone": "ri-contacts-line"},
    "criteres": {"libelle": "Critères administratifs", "icone": "ri-file-list-3-line"},
    "freins": {"libelle": "Freins identifiés", "icone": "ri-error-warning-line"},
    "pieces": {"libelle": "Pièces jointes", "icone": "ri-attachment-2"},
}

# Data an offreur can request, in display order. The identity is a single consent shown on several lines.
DONNEES = {
    IDENTITE: {
        "bloc": "identification",
        "libelle": "Identité",
        "description": "Vos nom, prénom, date de naissance et adresse, tels que connus par FranceConnect.",
        "source": "franceconnect",
        "lignes": {
            "prenom": "Prénom",
            "nom": "Nom",
            "date_naissance": "Date de naissance",
            "adresse": "Adresse postale",
        },
    },
    EMAIL: {
        "bloc": "contact",
        "libelle": "Adresse e-mail",
        "description": "L’adresse e-mail de votre compte FranceConnect.",
        "source": "franceconnect",
    },
    TELEPHONE: {
        "bloc": "contact",
        "libelle": "Téléphone",
        "description": "Le numéro de téléphone connu par France Travail.",
        "source": "france_travail",
    },
    STATUT_RSA: {
        "bloc": "criteres",
        "libelle": "Statut RSA",
        "description": "Si vous percevez le RSA, et depuis quand. Le montant n’est jamais transmis.",
        "source": "caf",
    },
    AAH: {
        "bloc": "criteres",
        "libelle": "AAH",
        "description": "Si vous percevez l’allocation aux adultes handicapés. Le montant n’est jamais transmis.",
        "source": "caf",
    },
    ASS: {
        "bloc": "criteres",
        "libelle": "ASS",
        "description": "Si vous percevez l’allocation de solidarité spécifique.",
        "source": "france_travail",
    },
    STATUT_EMPLOI: {
        "bloc": "criteres",
        "libelle": "Statut emploi",
        "description": "Si vous êtes en emploi ou sans emploi, et depuis quand.",
        "source": "france_travail",
    },
    STATUT_DEMANDEUR_EMPLOI: {
        "bloc": "criteres",
        "libelle": "Inscription France Travail",
        "description": "Si vous êtes inscrite ou inscrit comme demandeur d’emploi, votre catégorie et depuis quand.",
        "source": "france_travail",
    },
    RQTH: {
        "bloc": "criteres",
        "libelle": "RQTH",
        "description": "Si vous avez une reconnaissance de la qualité de travailleur handicapé, et jusqu’à quand.",
        "source": "mdph",
    },
    PASS_IAE: {
        "bloc": "criteres",
        "libelle": "PASS\u00a0IAE",
        "description": "Si vous avez un parcours en insertion en cours, et jusqu’à quand.",
        "source": "plateforme",
    },
    MOBILITE: {
        "bloc": "freins",
        "libelle": "Mobilité",
        "description": "Vos moyens de déplacement, tels que connus par France Travail.",
        "source": "france_travail",
    },
    GARDE_ENFANTS: {
        "bloc": "freins",
        "libelle": "Garde d’enfants",
        "description": "Si vous avez besoin d’une solution de garde, telle que connue par France Travail.",
        "source": "france_travail",
    },
    NUMERIQUE: {
        "bloc": "freins",
        "libelle": "Numérique",
        "description": "Votre autonomie sur les démarches en ligne.",
        "source": "plateforme",
    },
    CV: {
        "bloc": "pieces",
        "libelle": "CV",
        "description": "Le CV déposé sur la Plateforme de l’inclusion.",
        "source": "plateforme",
    },
    JUSTIFICATIF_DOMICILE: {
        "bloc": "pieces",
        "libelle": "Bail ou justificatif de domicile",
        "description": "Le justificatif de domicile que vous avez envoyé.",
        "source": "usager",
    },
    AVIS_FISCAL: {
        "bloc": "pieces",
        "libelle": "Avis fiscal",
        "description": "Votre dernier avis d’imposition, tel que connu par FranceConnect.",
        "source": "franceconnect",
    },
}

# Consents that do not share data with the offreur but allow an action
AUTORISATIONS = {
    INFORMER_PRESCRIPTEUR: {
        "libelle": "Prévenir mon conseiller",
        "description": "Votre conseiller ou conseillère est informé que cette structure vous accompagne.",
    },
    SUIVI_LONG: {
        "libelle": "Suivi dans le temps",
        "description": (
            "La structure peut connaître votre situation (emploi, formation) 3, 6 et 12 mois après "
            "votre accompagnement, pour mesurer son impact."
        ),
    },
}


def libelle(cle):
    """Return the human label of a catalogue key."""
    return {**DONNEES, **AUTORISATIONS}.get(cle, {}).get("libelle", cle)


def source(cle):
    """Return the source (label, icon, badge class) of a data key."""
    return SOURCES[DONNEES[cle]["source"]]


def par_bloc(cles):
    """Group data keys by block, in catalogue order: [(bloc_key, bloc, [(cle, donnee), …]), …]."""
    groupes = []
    for bloc_cle, bloc in BLOCS.items():
        donnees = [(cle, donnee) for cle, donnee in DONNEES.items() if donnee["bloc"] == bloc_cle and cle in cles]
        if donnees:
            groupes.append((bloc_cle, bloc, donnees))
    return groupes
