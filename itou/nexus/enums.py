from django.db import models

from itou.companies.enums import CompanyKind
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import UserKind


class Service(models.TextChoices):
    COMMUNAUTE = "la-communaute", "La communauté de l’inclusion"
    DATA_INCLUSION = "data-inclusion", "Data inclusion"
    DORA = "dora", "Dora"
    EMPLOIS = "les-emplois", "les emplois de l’inclusion"
    MARCHE = "le-marche", "Le marché de l’inclusion"
    MON_RECAP = "mon-recap", "Mon Récap"
    PILOTAGE = "pilotage", "Le pilotage de l’inclusion"

    @classmethod
    def activable(cls):
        """Returns the ordered services as displayed in the dashboard"""
        return [
            cls.EMPLOIS,
            cls.DORA,
            cls.MARCHE,
            cls.MON_RECAP,
            cls.PILOTAGE,
            cls.COMMUNAUTE,
        ]


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


emplois_kind_mapping = {
    UserKind.EMPLOYER: NexusUserKind.FACILITY_MANAGER,
    UserKind.PRESCRIBER: NexusUserKind.GUIDE,
}
USER_KIND_MAPPING = {
    Service.EMPLOIS: emplois_kind_mapping,
    Service.DORA: {
        "accompagnateur": NexusUserKind.GUIDE,
        "offreur": NexusUserKind.FACILITY_MANAGER,
        "accompagnateur_offreur": NexusUserKind.FACILITY_MANAGER,
        "autre": "",
        "": "",
    },
    Service.COMMUNAUTE: {
        "": "",  # this service does not have a user kind
    },
    Service.PILOTAGE: emplois_kind_mapping,
    Service.MON_RECAP: {
        # this service does not have a user kind
        UserKind.EMPLOYER: "",
        UserKind.PRESCRIBER: "",
    },
    Service.MARCHE: {
        "SIAE": NexusUserKind.FACILITY_MANAGER,
    },
}


STRUCTURE_KIND_MAPPING = {
    Service.EMPLOIS: {
        PrescriberOrganizationKind.AFPA: NexusStructureKind.AFPA,
        PrescriberOrganizationKind.ASE: NexusStructureKind.ASE,
        PrescriberOrganizationKind.ORIENTEUR: "",
        PrescriberOrganizationKind.CAARUD: NexusStructureKind.CAARUD,
        PrescriberOrganizationKind.CADA: NexusStructureKind.CADA,
        PrescriberOrganizationKind.CAF: NexusStructureKind.CAF,
        PrescriberOrganizationKind.CAP_EMPLOI: NexusStructureKind.CAP_EMPLOI,
        PrescriberOrganizationKind.CAVA: NexusStructureKind.CAVA,
        PrescriberOrganizationKind.CCAS: NexusStructureKind.CCAS_CIAS,
        PrescriberOrganizationKind.CHRS: NexusStructureKind.CHRS,
        PrescriberOrganizationKind.CHU: NexusStructureKind.CHU,
        PrescriberOrganizationKind.CIDFF: NexusStructureKind.CIDFF,
        PrescriberOrganizationKind.CPH: NexusStructureKind.CPH,
        PrescriberOrganizationKind.CSAPA: NexusStructureKind.CSAPA,
        PrescriberOrganizationKind.E2C: NexusStructureKind.E2C,
        PrescriberOrganizationKind.EPIDE: NexusStructureKind.EPIDE,
        PrescriberOrganizationKind.FT: NexusStructureKind.FT,
        PrescriberOrganizationKind.HUDA: NexusStructureKind.HUDA,
        PrescriberOrganizationKind.ML: NexusStructureKind.ML,
        PrescriberOrganizationKind.MSA: NexusStructureKind.MSA,
        PrescriberOrganizationKind.OACAS: NexusStructureKind.OACAS,
        PrescriberOrganizationKind.OIL: NexusStructureKind.OIL,
        PrescriberOrganizationKind.ODC: NexusStructureKind.OCD,
        PrescriberOrganizationKind.OHPD: NexusStructureKind.OCD,
        PrescriberOrganizationKind.OCASF: NexusStructureKind.OCASF,
        PrescriberOrganizationKind.PENSION: NexusStructureKind.PENSION,
        PrescriberOrganizationKind.PIJ_BIJ: NexusStructureKind.PIJ_BIJ,
        PrescriberOrganizationKind.PJJ: NexusStructureKind.PJJ,
        PrescriberOrganizationKind.PLIE: NexusStructureKind.PLIE,
        PrescriberOrganizationKind.RS_FJT: NexusStructureKind.RS_FJT,
        PrescriberOrganizationKind.PREVENTION: NexusStructureKind.CSAPA,
        PrescriberOrganizationKind.DEPT: NexusStructureKind.DEPT,
        PrescriberOrganizationKind.SPIP: NexusStructureKind.SPIP,
        PrescriberOrganizationKind.OTHER: "",
        CompanyKind.ACI: NexusStructureKind.ACI,
        CompanyKind.AI: NexusStructureKind.AI,
        CompanyKind.EA: NexusStructureKind.EA,
        CompanyKind.EATT: NexusStructureKind.EATT,
        CompanyKind.EI: NexusStructureKind.EI,
        CompanyKind.EITI: NexusStructureKind.EITI,
        CompanyKind.ETTI: NexusStructureKind.ETTI,
        CompanyKind.GEIQ: NexusStructureKind.GEIQ,
        CompanyKind.OPCS: NexusStructureKind.OPCS,
    },
    Service.DORA: {
        "ACI": NexusStructureKind.ACI,
        "ACIPHC": NexusStructureKind.ACI,
        "AFPA": NexusStructureKind.AFPA,
        "AI": NexusStructureKind.AI,
        "ASE": NexusStructureKind.ASE,
        "ASSO": NexusStructureKind.ASSO,
        "ASSO_CHOMEUR": NexusStructureKind.ASSO,
        "Autre": "",
        "AVIP": NexusStructureKind.AVIP,
        "BIB": NexusStructureKind.BIB,
        "CAARUD": NexusStructureKind.CAARUD,
        "CADA": NexusStructureKind.CADA,
        "CAF": NexusStructureKind.CAF,
        "CAP_EMPLOI": NexusStructureKind.CAP_EMPLOI,
        "CAVA": NexusStructureKind.CAVA,
        "CC": NexusStructureKind.COMMUNES,
        "CCAS": NexusStructureKind.CCAS_CIAS,
        "CCONS": NexusStructureKind.CCONS,
        "CD": NexusStructureKind.DEPT,
        "CDAS": NexusStructureKind.DEPT,
        "CFP": NexusStructureKind.CFP,
        "CHRS": NexusStructureKind.CHRS,
        "CHU": NexusStructureKind.CHU,
        "CIAS": NexusStructureKind.CCAS_CIAS,
        "CIDFF": NexusStructureKind.CIDFF,
        "CITMET": NexusStructureKind.CCONS,
        "CMP": NexusStructureKind.CMP,
        "CMS": NexusStructureKind.CMS,
        "CPAM": NexusStructureKind.CPAM,
        "CPH": NexusStructureKind.CPH,
        "CS": NexusStructureKind.CCAS_CIAS,
        "CSAPA": NexusStructureKind.CSAPA,
        "CSC": NexusStructureKind.CCAS_CIAS,
        "DEETS": NexusStructureKind.REG,
        "DEPT": NexusStructureKind.DEPT,
        "DIPLP": "",
        "E2C": NexusStructureKind.E2C,
        "EA": NexusStructureKind.EA,
        "EATT": NexusStructureKind.EATT,
        "EI": NexusStructureKind.EI,
        "EITI": NexusStructureKind.EITI,
        "ENM": NexusStructureKind.GEN,
        "EPCI": NexusStructureKind.COMMUNES,
        "EPI": "",
        "EPIDE": NexusStructureKind.EPIDE,
        "EPN": NexusStructureKind.EPN,
        "ES": NexusStructureKind.ASSO,
        "ESS": NexusStructureKind.ASSO,
        "ETABL_PRI": NexusStructureKind.ETABL_PRI,
        "ETABL_PUB": NexusStructureKind.ETABL_PUB,
        "ETAT": NexusStructureKind.ETABL_PUB,
        "ETTI": NexusStructureKind.ETTI,
        "EVS": NexusStructureKind.ASSO,
        "FABLAB": NexusStructureKind.ASSO,
        "FAIS": NexusStructureKind.FAS,
        "FT": NexusStructureKind.FT,
        "GEIQ": NexusStructureKind.GEIQ,
        "HUDA": NexusStructureKind.HUDA,
        "LA_POSTE": NexusStructureKind.POSTE,
        "MDA": "",
        "MDE": NexusStructureKind.MDE,
        "MDEF": NexusStructureKind.MDE,
        "MDPH": NexusStructureKind.DEPT,
        "MDS": NexusStructureKind.MDS,
        "MJC": NexusStructureKind.MJC,
        "ML": NexusStructureKind.ML,
        "MQ": NexusStructureKind.COMMUNES,
        "MSA": NexusStructureKind.MSA,
        "MSAP": NexusStructureKind.MSAP,
        "MUNI": NexusStructureKind.COMMUNES,
        "OACAS": NexusStructureKind.OACAS,
        "ODC": NexusStructureKind.OCD,
        "OF": NexusStructureKind.OF,
        "OIL": NexusStructureKind.OIL,
        "OPCS": NexusStructureKind.OPCS,
        "PAD": NexusStructureKind.ETABL_PUB,
        "PENSION": NexusStructureKind.PENSION,
        "PI": NexusStructureKind.PIJ_BIJ,
        "PIJ_BIJ": NexusStructureKind.PIJ_BIJ,
        "PIMMS": NexusStructureKind.PIMMS,
        "PJJ": NexusStructureKind.PJJ,
        "PLIE": NexusStructureKind.PLIE,
        "PREF": NexusStructureKind.REG,
        "PREVENTION": NexusStructureKind.CSAPA,
        "REG": NexusStructureKind.REG,
        "RESSOURCERIE": NexusStructureKind.ASSO,
        "RFS": NexusStructureKind.RFS,
        "RS_FJT": NexusStructureKind.RS_FJT,
        "SCP": NexusStructureKind.CCONS,
        "SPIP": NexusStructureKind.SPIP,
        "TIERS_LIEUX": NexusStructureKind.ASSO,
        "UDAF": NexusStructureKind.DEPT,
    },
    Service.MARCHE: {
        "EI": NexusStructureKind.EI,
        "AI": NexusStructureKind.AI,
        "ACI": NexusStructureKind.ACI,
        "ETTI": NexusStructureKind.ETTI,
        "EITI": NexusStructureKind.EITI,
        "GEIQ": NexusStructureKind.GEIQ,
        "EA": NexusStructureKind.EA,
        "EATT": NexusStructureKind.EATT,
        "ESAT": NexusStructureKind.ESAT,
        "SEP": NexusStructureKind.SPIP,
        "OPCS": NexusStructureKind.OPCS,
    },
}
