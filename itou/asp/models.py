import re
from enum import Enum

from unidecode import unidecode


class LaneType(Enum):
    """
    Lane type

    Import/translation of ASP ref file: ref_type_voie_v3.csv
    """

    AER = "Aérodrome"
    AGL = "Agglomération"
    AIRE = "Aire"
    ALL = "Allée"
    ACH = "Ancien chemin"
    ART = "Ancienne route"
    AV = "Avenue"
    BEGI = "Beguinage"
    BD = "Boulevard"
    BRG = "Bourg"
    CPG = "Camping"
    CAR = "Carrefour"
    CTRE = "Centre"
    CCAL = "Centre commercial"
    CHT = "Chateau"
    CHS = "Chaussee"
    CHEM = "Chemin"
    CHV = "Chemin vicinal"
    CITE = "Cité"
    CLOS = "Clos"
    CTR = "Contour"
    COR = "Corniche"
    COTE = "Coteaux"
    COUR = "Cour"
    CRS = "Cours"
    DSC = "Descente"
    DOM = "Domaine"
    ECL = "Ecluse"
    ESC = "Escalier"
    ESPA = "Espace"
    ESP = "Esplanade"
    FG = "Faubourg"
    FRM = "Ferme"
    FON = "Fontaine"
    GAL = "Galerie"
    GARE = "Gare"
    GBD = "Grand boulevard"
    GPL = "Grande place"
    GR = "Grande rue"
    GRI = "Grille"
    HAM = "Hameau"
    IMM = "Immeuble(s)"
    IMP = "Impasse"
    JARD = "Jardin"
    LD = "Lieu-dit"
    LOT = "Lotissement"
    MAIL = "Mail"
    MAIS = "Maison"
    MAS = "Mas"
    MTE = "Montee"
    PARC = "Parc"
    PRV = "Parvis"
    PAS = "Passage"
    PLE = "Passerelle"
    PCH = "Petit chemin"
    PRT = "Petite route"
    PTR = "Petite rue"
    PL = "Place"
    PTTE = "Placette"
    PLN = "Plaine"
    PLAN = "Plan"
    PLT = "Plateau"
    PONT = "Pont"
    PORT = "Port"
    PROM = "Promenade"
    QUAI = "Quai"
    QUAR = "Quartier"
    RPE = "Rampe"
    REMP = "Rempart"
    RES = "Residence"
    ROC = "Rocade"
    RPT = "Rond-point"
    RTD = "Rotonde"
    RTE = "Route"
    RUE = "Rue"
    RLE = "Ruelle"
    SEN = "Sente"
    SENT = "Sentier"
    SQ = "Square"
    TPL = "Terre plein"
    TRAV = "Traverse"
    VEN = "Venelle"
    VTE = "Vieille route"
    VCHE = "Vieux chemin"
    VILL = "Villa"
    VLGE = "Village"
    VOIE = "Voie"
    ZONE = "Zone"
    ZA = "Zone d'activite"
    ZAC = "Zone d'amenagement concerte"
    ZAD = "Zone d'amenagement differe"
    ZI = "Zone industrielle"
    ZUP = "Zone urbanisation prio"

    @classmethod
    def with_similar_name(cls, name):
        "Returns enum with similar name"
        return cls.__members__.get(name.upper)

    @classmethod
    def with_similar_value(cls, value):
        "Returns enum with a similar value"
        revert_map = {unidecode(lt.value.lower()): lt for lt in cls}
        return revert_map.get(value)


# Even if geo API does a great deal of a job,
# it sometimes shows unexpected result labels for lane types
# like 'r' for 'rue', or 'Av' for 'Avenue', etc.
# This a still incomplete mapping of these variations
_LANE_TYPE_ALIASES = {
    "^r": LaneType.RUE,
    "^che": LaneType.CHEM,
    "^grande?[ \-']rue": LaneType.GR,  # noqa W605
    "^qu": LaneType.QUAI,
    "^voies": LaneType.VOIE,
    "^domaines": LaneType.DOM,
    "^allees": LaneType.ALL,
    "^lieu?[ -]dit": LaneType.LD,
}


def find_lane_type_aliases(alias):
    """Alternative lookup of some lane types.
       Help improving overall quality of ASP address formatting"""
    for regx, lane_type in _LANE_TYPE_ALIASES.items():
        if re.search(regx, alias.lower()):
            return lane_type
    return None


class LaneExtension(Enum):
    """
    Lane extension

    Import/translation of ASP ref file: ref_extension_voie_v1.csv
    """

    B = "Bis"
    T = "Ter"
    Q = "Quater"
    C = "Quinquies"

    @classmethod
    def with_similar_name_or_value(cls, s, fmt=str.lower):
        for elt in cls:
            test = fmt(s)
            if test == fmt(elt.name) or test == fmt(elt.value):
                return elt
        return None
