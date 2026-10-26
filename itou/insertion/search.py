from django.utils.text import slugify


CONCATENATED_TOKEN_PREFIX = "zz"

# Copied from data·inclusion, keep in sync:
# https://github.com/gip-inclusion/data-inclusion/blob/main/api/src/data_inclusion/api/inclusion_data/services.py
THEMATIC_ALIASES = {
    "choisir-un-metier--confirmer-son-choix-de-metier": ("immersion", "mise en situation", "stage"),
    "choisir-un-metier--connaitre-les-opportunites-demploi": (
        "débouchés",
        "emploi local",
        "marché du travail",
        "secteurs qui recrutent",
    ),
    "choisir-un-metier--decouvrir-un-metier-ou-un-secteur-dactivite": (
        "découverte métier",
        "forum métiers",
        "reconversion",
    ),
    "choisir-un-metier--identifier-ses-points-forts-et-ses-competences": (
        "bilan de compétences",
        "savoir-faire",
        "évaluation",
    ),
    "creer-une-entreprise--definir-son-projet-de-creation-dentreprise": (
        "auto-entrepreneur",
        "entrepreneur",
        "freelance",
        "micro-entreprise",
    ),
    "creer-une-entreprise--developper-son-entreprise": (
        "croissance",
        "développement commercial",
        "gestion entreprise",
    ),
    "creer-une-entreprise--structurer-son-projet-de-creation-dentreprise": ("business plan", "statut juridique"),
    "difficultes-administratives-ou-juridiques--accompagnement-aux-demarches-administratives": (
        "administratif",
        "formalités",
    ),
    "difficultes-administratives-ou-juridiques--accompagnement-pour-lacces-a-la-citoyennete": (
        "naturalisation",
        "titre de séjour",
        "vie civique",
    ),
    "difficultes-administratives-ou-juridiques--prendre-en-compte-une-problematique-judiciaire": (
        "avocat",
        "juridique",
        "justice",
        "recours",
    ),
    "difficultes-financieres--acquerir-une-autonomie-budgetaire": ("compte bancaire", "gestion argent", "épargne"),
    "difficultes-financieres--ameliorer-sa-gestion-budgetaire": ("budget", "finance", "trésorerie"),
    "difficultes-financieres--mettre-en-place-une-mesure-de-protection-financiere": (
        "curatelle",
        "protection juridique",
        "tutelle",
    ),
    "difficultes-financieres--prevenir-une-degradation-de-la-situation-financiere": ("microcrédit", "prêt solidaire"),
    "difficultes-financieres--situation-dendettement-surendettement": ("dette", "impayé"),
    "equipement-et-alimentation--aide-menagere": ("aide à domicile", "entretien logement"),
    "equipement-et-alimentation--alimentation": ("alimentaire", "repas"),
    "famille--garde-denfants": ("assistante maternelle", "crèche", "nourrice"),
    "famille--prise-en-charge-personne-dependante": ("aidant", "aide soignant", "personne âgée"),
    "famille--soutien-a-la-parentalite-et-a-leducation": ("famille",),
    "famille--soutien-aidants": ("aide soignant", "handicap"),
    "famille--surmonter-conflits-separation-violence": ("divorce", "pension alimentaire"),
    "lecture-ecriture-calcul--maitriser-le-calcul": ("remise à niveau", "savoirs fondamentaux"),
    "lecture-ecriture-calcul--maitriser-le-francais": (
        "alphabétisation",
        "cours de français",
        "fle",
        "français langue étrangère",
        "illettrisme",
    ),
    "logement-hebergement--acheter-un-logement": ("prêt immobilier",),
    "logement-hebergement--changer-de-logement": ("déménagement",),
    "logement-hebergement--louer-un-logement": ("bail", "hlm", "logements sociaux"),
    "logement-hebergement--rechercher-une-solution-dhebergement-temporaire": (
        "centre d'accueil",
        "foyer",
        "sans-abri",
    ),
    "logement-hebergement--reduire-les-impayes-de-loyer": ("expulsion", "impayé"),
    "logement-hebergement--se-maintenir-dans-le-logement": ("insalubrité", "rénovation", "travaux"),
    "logement-hebergement--sinformer-sur-les-demarches-liees-a-lacces-au-logement": ("domiciliation",),
    "mobilite--acceder-a-un-vehicule": ("deux-roues", "voiture", "location voiture"),
    "mobilite--entretenir-reparer-son-vehicule": ("contrôle technique", "garage", "réparation"),
    "mobilite--etre-accompagne-dans-son-parcours-mobilite": ("déplacement", "itinéraire", "trajet"),
    "mobilite--financer-ma-mobilite": ("aide transport",),
    "mobilite--mobilite-douce-partagee-collective": ("bus", "covoiturage", "transport", "trottinette", "vélo"),
    "mobilite--preparer-un-permis": ("auto-école", "code de la route", "conduite"),
    "numerique--acceder-a-des-services-en-ligne": ("dématérialisation", "informatique", "internet"),
    "numerique--acceder-a-une-connexion-internet": ("wifi",),
    "numerique--acquerir-un-equipement": ("ordinateur", "smartphone", "tablette"),
    "numerique--maitriser-les-fondamentaux-du-numerique": ("bureautique", "digital", "illectronisme"),
    "preparer-sa-candidature--developper-son-reseau": ("mentorat", "parrainage"),
    "preparer-sa-candidature--organiser-ses-demarches-de-recherche-demploi": ("candidature",),
    "preparer-sa-candidature--realiser-un-cv-et-ou-une-lettre-de-motivation": ("portfolio",),
    "preparer-sa-candidature--valoriser-ses-competences": ("bilan de compétences", "validation acquis"),
    "remobilisation--activites-sportives-et-culturelles": ("arts", "atelier créatif", "loisirs"),
    "remobilisation--benevolat-action-citoyenne": ("service civique", "volontariat"),
    "remobilisation--bien-etre-confiance-en-soi": ("estime de soi",),
    "remobilisation--lien-social": ("socialisation",),
    "sante--acces-aux-soins": ("hygiène", "médecin", "santé"),
    "sante--addictions": ("alcool", "drogue", "sevrage", "désintoxication"),
    "sante--constituer-un-dossier-mdph-invalidite": ("handicap", "rqth"),
    "sante--sante-mentale": ("psychologue", "thérapie", "psychiatre", "cmp"),
    "sante--sante-sexuelle": ("contraception", "dépistage", "planning familial"),
    "se-former--monter-son-dossier-de-formation": ("certification", "cpf", "financement formation"),
    "se-former--trouver-sa-formation": ("certification", "cpf"),
    "souvrir-a-linternational--connaitre-les-opportunites-demploi-a-letranger": (
        "expatriation",
        "international",
        "visa",
    ),
    "souvrir-a-linternational--sinformer-sur-les-aides-pour-travailler-a-letranger": (
        "mobilité européenne",
        "mobilité internationale",
    ),
    "souvrir-a-linternational--sorganiser-suite-a-son-retour-en-france": ("rapatriement",),
    "trouver-un-emploi--convaincre-un-recruteur-en-entretien": ("entretien embauche", "pitch", "simulation entretien"),
    "trouver-un-emploi--faire-des-candidatures-spontanees": ("démarchage", "prospection"),
    "trouver-un-emploi--maintien-dans-lemploi": ("travail",),
    "trouver-un-emploi--repondre-a-des-offres-demploi": ("candidature", "embauche", "recrutement"),
}


def concatenated_token(text):
    # Why: multi-word aliases are indexed as a single token so that they only match as a whole expression.
    return CONCATENATED_TOKEN_PREFIX + slugify(text).replace("-", "")


SINGLE_WORD_ALIASES = {
    code: " ".join(alias for alias in aliases if " " not in alias) for code, aliases in THEMATIC_ALIASES.items()
}
CONCATENATED_ALIASES = {
    code: " ".join(concatenated_token(alias) for alias in aliases if " " in alias)
    for code, aliases in THEMATIC_ALIASES.items()
}
