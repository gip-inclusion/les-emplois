from django.db import models

from itou.users.enums import UserKind


class Service(models.TextChoices):
    COMMUNAUTE = "la-communauté", "La communauté"
    DATA_INCLUSION = "data-inclusion", "Data inclusion"
    DORA = "dora", "Dora"
    EMPLOIS = "les-emplois", "les emplois"
    MARCHE = "le-marche", "Le marché"
    MON_RECAP = "mon-recap", "Mon Recap"
    PILOTAGE = "pilotage", "Le pilotage"


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
    ACI = "ACI"
    ACIPHC = "ACIPHC"
    AFPA = "AFPA"
    AI = "AI"
    ASE = "ASE"
    ASSO = "ASSO"
    ASSO_CHOMEUR = "ASSO_CHOMEUR"
    AVIP = "AVIP"
    BIB = "BIB"
    CAARUD = "CAARUD"
    CADA = "CADA"
    CAF = "CAF"
    CAP_EMPLOI = "CAP_EMPLOI"
    CAVA = "CAVA"
    CCAS = "CCAS"
    CC = "CC"
    CCONS = "CCONS"
    CDAS = "CDAS"
    CD = "CD"
    CHRS = "CHRS"
    CHU = "CHU"
    CIAS = "CIAS"
    CIDFF = "CIDFF"
    CITMET = "CITMET"
    CMP = "CMP"
    CMS = "CMS"
    CPAM = "CPAM"
    CPH = "CPH"
    CSAPA = "CSAPA"
    CSC = "CSC"
    CS = "CS"
    DEETS = "DEETS"
    DEPT = "DEPT"
    E2C = "E2C"
    EA = "EA"
    EATT = "EATT"
    EI = "EI"
    EITI = "EITI"
    ENM = "ENM"
    EPCI = "EPCI"
    EPIDE = "EPIDE"
    EPN = "EPN"
    ESAT = "ESAT"
    ES = "ES"
    ESS = "ESS"
    ETABL_PRI = "ETABL_PRI"
    ETABL_PUB = "ETABL_PUB"
    ETAT = "ETAT"
    ETTI = "ETTI"
    EVS = "EVS"
    FABLAB = "FABLAB"
    FAIS = "FAIS"
    FT = "FT"
    GEIQ = "GEIQ"
    HUDA = "HUDA"
    LA_POSTE = "LA_POSTE"
    MDEF = "MDEF"
    MDE = "MDE"
    MDPH = "MDPH"
    MDS = "MDS"
    MJC = "MJC"
    ML = "ML"
    MQ = "MQ"
    MSA = "MSA"
    MSAP = "MSAP"
    MUNI = "MUNI"
    OACAS = "OACAS"
    OCASF = "OCASF"
    ODC = "ODC"
    OF = "OF"
    OHPD = "OHPD"
    OIL = "OIL"
    OPCS = "OPCS"
    OTHER = "Autre"
    PAD = "PAD"
    PENSION = "PENSION"
    PIJ_BIJ = "PIJ_BIJ"
    PIMMS = "PIMMS"
    PI = "PI"
    PJJ = "PJJ"
    PLIE = "PLIE"
    PREF = "PREF"
    PREVENTION = "PREVENTION"
    REG = "REG"
    RESSOURCERIE = "RESSOURCERIE"
    RFS = "RFS"
    RS_FJT = "RS_FJT"
    SCP = "SCP"
    SEP = "SEP"
    SPIP = "SPIP"
    TIERS_LIEUX = "TIERS_LIEUX"
    UDAF = "UDAF"


USER_KIND_MAPPING = {
    Service.EMPLOIS: {
        UserKind.EMPLOYER: NexusUserKind.FACILITY_MANAGER,
        UserKind.PRESCRIBER: NexusUserKind.GUIDE,
    },
    Service.DORA: {
        "accompagnateur": NexusUserKind.GUIDE,
        "offreur": NexusUserKind.FACILITY_MANAGER,
        "accompagnateur_offreur": NexusUserKind.FACILITY_MANAGER,
        "autre": "",
    },
    Service.COMMUNAUTE: {
        "": "",
    },
    Service.PILOTAGE: {
        UserKind.EMPLOYER: NexusUserKind.FACILITY_MANAGER,
        UserKind.PRESCRIBER: NexusUserKind.GUIDE,
    },
    Service.MON_RECAP: {
        "": "",
    },
    Service.MARCHE: {
        "SIAE": NexusUserKind.FACILITY_MANAGER,
    },
}
