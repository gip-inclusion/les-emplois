from django.db import models


class Service(models.TextChoices):
    COMMUNAUTE = "la-communaute", "La communauté de l’inclusion"
    DATA_INCLUSION = "data-inclusion", "Data inclusion"
    DORA = "dora", "Dora"
    EMPLOIS = "les-emplois", "les emplois de l’inclusion"
    MARCHE = "le-marche", "Le marché de l’inclusion"
    MON_RECAP = "mon-recap", "Mon Récap"
    PILOTAGE = "pilotage", "Le pilotage de l’inclusion"


class Auth(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    MAGIC_LINK = "MAGIC_LINK", "Lien magique"
    INCLUSION_CONNECT = "INCLUSION_CONNECT", "Inclusion Connect"
    PRO_CONNECT = "PRO_CONNECT", "ProConnect"


class Role(models.TextChoices):
    ADMINISTRATOR = "ADMINISTRATOR", "Administrateur"
    COLLABORATOR = "COLLABORATOR", "Collaborateur"


class NexusUserKind(models.TextChoices):
    FACILITY_MANAGER = "FACILITY_MANAGER", "Gestionnaire de structure"
    GUIDE = "GUIDE", "Accompagnateur"


class NexusStructureKind(models.TextChoices):
    ACI = "ACI", "Atelier chantier d'insertion"
    AFPA = "AFPA", "AFPA - Agence nationale pour la formation professionnelle des adultes"
    AI = "AI", "Association intermédiaire"
    ASE = "ASE", "ASE - Aide sociale à l'enfance"
    ASSO = "ASSO", "Association"
    AVIP = "AVIP", "Crèches AVIP"
    BIB = "BIB", "Bibliothèque / Médiathèque"
    CAARUD = (
        "CAARUD",
        ("CAARUD - Centre d'accueil et d'accompagnement à la réduction de risques pour usagers de drogues"),
    )
    CADA = "CADA", "CADA - Centre d'accueil de demandeurs d'asile"
    CAF = "CAF", "CAF - Caisse d'allocations familiales"
    CAP_EMPLOI = "CAP_EMPLOI", "Cap emploi - Réseau Cheops"
    CAVA = "CAVA", "CAVA - Centre d'adaptation à la vie active"
    CCAS_CIAS = "CCAS_CIAS", "Centre communal d'action sociale ou centre intercommunal d'action sociale"
    CCONS = "CCONS", "Chambres consulaires"
    CHRS = "CHRS", "CHRS - Centre d'hébergement et de réinsertion sociale"
    CHU = "CHU", "CHU - Centre d'hébergement d'urgence"
    CIDFF = "CIDFF", "CIDFF - Centre d'information sur les droits des femmes et des familles"
    CMP = "CMP", "Centre Médico-Psychologique"
    CMS = "CMS", "Centre Médico-Social"
    COMMUNES = "COMMUNES", "Communes"
    CFP = "CFP", "Centre des Finances Publiques"
    CPAM = "CPAM", "Caisse Primaire d’Assurance Maladie"
    CPH = "CPH", "Centres provisoires d’hébergement"
    CSAPA = "CSAPA", "CSAPA - Centre de soins, d'accompagnement et de prévention en addictologie"
    DEPT = "DEPT", "Départements"
    E2C = "E2C", "Écoles de la deuxième chance"
    EA = "EA", "Entreprise adaptée"
    EATT = "EATT", "Entreprise adaptée de travail temporaire"
    EI = "EI", "Entreprise d'insertion"
    EITI = "EITI", "Entreprise d'insertion par le travail indépendant"
    EPIDE = "EPIDE", "EPIDE - Établissement pour l'insertion dans l'emploi"
    ESAT = "ESAT", "ESAT - Établissements ou services d'accompagnement par le travail"
    EPN = "EPN", "Espaces publics numériques"
    ETABL_PRI = "ETABL_PRI", "Établissement privé"
    ETABL_PUB = "ETABL_PUB", "Établissement public"
    ETTI = "ETTI", "Entreprise de travail temporaire d'insertion"
    FAS = "FAS", "Fédération des acteurs de la solidarité"
    FT = "FT", "France Travail"
    GEIQ = "GEIQ", "Groupement d'employeurs pour l'insertion et la qualification"
    GEN = "GEN", "Grandes écoles du numérique"
    HUDA = "HUDA", "HUDA - Hébergement d’urgence pour demandeurs d’asile"
    POSTE = "POSTE", "La Poste"
    MDE = "MDE", "Maisons de l'emploi"
    MDS = "MDS", "Maison des solidarités"
    ML = "ML", "Mission locale"
    MJC = "MJC", "MJC - Maison des jeunes et de la culture"
    MSAP = "MSAP", "Maison de Services Au Public"
    MSA = "MSA", "Mutualité sociale agricole"
    OACAS = (
        "OACAS",
        (
            "OACAS - Structure porteuse d'un agrément national organisme "
            "d'accueil communautaire et d'activité solidaire"
        ),
    )
    OCASF = "OCASF", "Organisme mentionné au 8° du I de l’article L. 312-1 du code de l’action sociale et des familles"
    OCD = "DCD", "Organisation délégataire d’un conseil départemental"
    OIL = "OIL", "Opérateur d'intermédiation locative"
    OPCS = "OPCS", "Organisation porteuse de la clause sociale"
    OF = "OF", "Organisme de formation"
    PENSION = "PENSION", "Pension de famille / résidence accueil"
    PIJ_BIJ = "PIJ_BIJ", "Points et bureaux information jeunesse"
    PIMMS = "PIMMS", "Pimms Médiation"
    PJJ = "PJJ", "PJJ - Protection judiciaire de la jeunesse"
    PLIE = "PLIE", "PLIE - Plans locaux pour l’insertion et l’emploi"
    REG = "REG", "Régions"
    RFS = "RFS", "Réseau France Service"
    RS_FJT = "RS_FJT", "Résidence sociale / FJT - Foyer de Jeunes Travailleurs"
    SPIP = "SPIP", "SPIP - Service pénitentiaire d'insertion et de probation"
