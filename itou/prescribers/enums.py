from django.db import models


class PrescriberOrganizationKind(models.TextChoices):
    # /!\ Keep this list alphabetically sorted to help users find the proper kind
    # cf test_prescriber_kinds_are_alphabetically_sorted test
    AFPA = "AFPA", "AFPA - Agence nationale pour la formation professionnelle des adultes"
    ASE = "ASE", "ASE - Aide sociale à l'enfance"
    ORIENTEUR = "Orienteur", "Autre organisation (orienteur)"
    CAARUD = (
        "CAARUD",
        ("CAARUD - Centre d'accueil et d'accompagnement à la réduction de risques pour usagers de drogues"),
    )
    CADA = "CADA", "CADA - Centre d'accueil de demandeurs d'asile"
    CAF = "CAF", "CAF - Caisse d'allocations familiales"
    CAP_EMPLOI = "CAP_EMPLOI", "Cap emploi"
    CAVA = "CAVA", "CAVA - Centre d'adaptation à la vie active"
    CCAS = ("CCAS", "CCAS - Centre communal d'action sociale ou centre intercommunal d'action sociale")
    CHRS = "CHRS", "CHRS - Centre d'hébergement et de réinsertion sociale"
    CHU = "CHU", "CHU - Centre d'hébergement d'urgence"
    CIDFF = ("CIDFF", "CIDFF - Centre d'information sur les droits des femmes et des familles")
    CPH = "CPH", "CPH - Centre provisoire d'hébergement"
    CSAPA = "CSAPA", "CSAPA - Centre de soins, d'accompagnement et de prévention en addictologie"
    E2C = "E2C", "E2C - École de la deuxième chance"
    EPIDE = "EPIDE", "EPIDE - Établissement pour l'insertion dans l'emploi"
    PE = "PE", "France Travail"  # Previously pôle emploi
    HUDA = "HUDA", "HUDA - Hébergement d'urgence pour demandeurs d'asile"
    ML = "ML", "Mission locale"
    MSA = "MSA", "MSA - Mutualité Sociale Agricole"
    OACAS = (
        "OACAS",
        (
            "OACAS - Structure porteuse d'un agrément national organisme "
            "d'accueil communautaire et d'activité solidaire"
        ),
    )
    OIL = "OIL", "Opérateur d'intermédiation locative"
    ODC = "ODC", "Organisation délégataire d'un Conseil Départemental (Orientation et suivi des BRSA)"
    OHPD = "OHPD", "Organisme habilité par le préfet de département"
    OCASF = "OCASF", "Organisme mentionné au 8° du I de l’article L. 312-1 du code de l’action sociale et des familles"
    PENSION = "PENSION", "Pension de famille / résidence accueil"
    PIJ_BIJ = "PIJ_BIJ", "PIJ-BIJ - Point/Bureau information jeunesse"
    PJJ = "PJJ", "PJJ - Protection judiciaire de la jeunesse"
    PLIE = "PLIE", "PLIE - Plan local pour l'insertion et l'emploi"
    RS_FJT = "RS_FJT", "Résidence sociale / FJT - Foyer de Jeunes Travailleurs"
    PREVENTION = "PREVENTION", "Service ou club de prévention"
    DEPT = "DEPT", "Service social du conseil départemental"
    SPIP = "SPIP", "SPIP - Service pénitentiaire d'insertion et de probation"

    OTHER = "Autre", "Autre"

    def to_PE_typologie_prescripteur(self):
        if self in PE_SENSITIVE_PRESCRIBER_KINDS:
            return PrescriberOrganizationKind.OTHER
        return self


HIDDEN_PRESCRIBER_KINDS = [
    PrescriberOrganizationKind.OHPD,
    PrescriberOrganizationKind.OCASF,
    PrescriberOrganizationKind.ORIENTEUR,
]

CHOOSABLE_PRESCRIBER_KINDS = [
    (k, v) for k, v in PrescriberOrganizationKind.choices if k not in HIDDEN_PRESCRIBER_KINDS
]

# Sensitive prescriber kinds that we do not want to send via PE API
PE_SENSITIVE_PRESCRIBER_KINDS = {
    PrescriberOrganizationKind.ASE,
    PrescriberOrganizationKind.CAARUD,
    PrescriberOrganizationKind.CIDFF,
    PrescriberOrganizationKind.CSAPA,
    PrescriberOrganizationKind.PENSION,
    PrescriberOrganizationKind.PJJ,
    PrescriberOrganizationKind.PREVENTION,
    PrescriberOrganizationKind.SPIP,
}


class PrescriberAuthorizationStatus(models.TextChoices):
    NOT_SET = "NOT_SET", "Habilitation en attente de validation"
    VALIDATED = "VALIDATED", "Habilitation validée"
    REFUSED = "REFUSED", "Validation de l'habilitation refusée"
    NOT_REQUIRED = "NOT_REQUIRED", "Pas d'habilitation nécessaire"


# DGPE, as in "Direction Générale Pôle emploi" is a special PE agency which oversees the whole country.
DGPE_SAFIR_CODE = "00162"

# DRPE, as in "Direction Régionale Pôle emploi", are special PE agencies which oversee their whole region.
# We keep it simple by hardcoding their (short) list here to avoid the complexity of adding a field or a kind.
DRPE_SAFIR_CODES = [
    "13992",  # Provence-Alpes-Côte d'Azur
    "20010",  # Corse
    "21069",  # Bourgogne-Franche-Comté
    "31096",  # Occitanie
    "33127",  # Nouvelle-Aquitaine
    "35076",  # Bretagne
    "44116",  # Pays de la Loire
    "45054",  # Centre-Val de Loire
    "59212",  # Hauts-de-France
    "67085",  # Grand Est
    "69188",  # Auvergne-Rhône-Alpes
    "75980",  # Île-de-France
    "76115",  # Normandie
    "97110",  # Guadeloupe
    "97210",  # Martinique
    "97310",  # Guyane
    "97410",  # La Réunion
    "97600",  # Mayotte
]

# DTPE, as in "Direction Territoriale Pôle emploi", are special PE agencies which generally oversee
# their whole department and sometimes more than one department.
# We keep it simple by hardcoding their list here to avoid the complexity of adding a field or a kind.
# By default (`None`) a DTPE oversees its own department unless a list of several departments is specified below.
DTPE_SAFIR_CODE_TO_DEPARTMENTS = {
    # Note that the first two digits of the SAFIR code usually indicate the department.
    "04016": ["04", "05"],
    "10038": None,
    "11030": ["09", "11"],
    "13010": None,
    "14056": None,
    "17041": ["16", "17"],
    "18029": None,
    "20423": None,
    "20431": None,
    "21265": None,
    "22045": None,
    "24036": ["19", "24"],
    "25019": ["25", "90"],
    "26085": None,
    "27002": None,
    "28004": None,
    "29110": None,
    "30600": ["30", "48"],
    "311": None,
    "31403": None,
    "33390": None,
    "34300": None,
    "35141": None,
    "37056": None,
    "38040": None,
    "40029": ["40", "47"],
    "4016": None,
    "42060": None,
    "44060": None,
    "45000": None,
    "49104": None,
    "51023": None,
    "54127": None,
    "56106": None,
    "57561": None,
    "59470": None,
    "6013": None,
    "60260": None,
    "62750": None,
    "63074": None,
    "64093": None,
    "65020": ["65", "32"],
    "66004": None,
    "67014": None,
    "68311": None,
    "69050": None,
    "70007": ["39", "70"],
    "71002": None,
    "72203": ["72", "53"],
    "73055": None,
    "74063": None,
    "75082": None,
    "76266": None,
    "77206": None,
    "78201": None,
    "80073": None,
    "8056": None,
    "81003": ["81", "12"],
    "82013": ["82", "46"],
    "83142": None,
    "84002": None,
    "85004": None,
    "86083": ["79", "86"],
    "87068": ["23", "87"],
    "88654": None,
    "89031": ["58", "89"],
    "91211": None,
    "92301": None,
    "93326": None,
    "94305": None,
    "951": None,
    "952": None,
    "95204": None,
    "97201": None,
    "97312": None,
    "97460": None,
    "97549": None,
    "97600": None,
    "97715": None,
    "97716": None,
}
