import re
from enum import Enum

from django.db import models
from unidecode import unidecode
from django.utils.translation import gettext_lazy as _


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


class PeriodMixinQuerySet(models.QuerySet):
    def current(self):
        return self.filter(end_date=None)


class PeriodMixin(models.Model):
    start_date = models.DateField(verbose_name=_("Début de validité"))
    end_date = models.DateField(verbose_name=_("Fin de validité"), null=True)

    class Meta:
        abstract = True


class CodeLabelMixin(models.Model):

    class Meta:
        abstract = True

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"{type(self).__name__}: pk={self.pk}, code={self.code}"


class AllocationDuration(models.TextChoices):
    """
    Translation of ASP ref file: ref_duree_allocation_emploi_v2.csv

    Note: effect periods are not handled
    """
    NONE = "", _("Aucune")
    LESS_THAN_6_MONTHS = "LESS_THAN_6_MONTHS", _("Moins de 6 mois")
    FROM_6_TO_11_MONTHS = "FROM_6_TO_11_MONTHS", _("De 6 à 11 mois")
    FROM_12_TO_23_MONTHS = "FROM_12_TO_23_MONTHS", _("De 12 à 23 mois")
    MORE_THAN_24_MONTHS = "MORE_THAN_24_MONTHS", _("24 mois et plus")


class EducationalLevel(PeriodMixin, CodeLabelMixin):
    """
    Education level of the employee

    Translation of ASP ref file: ref_niveau_formation_v3.csv
    """
    code = models.CharField(verbose_name=_("Code formation ASP"), max_length=2)
    name = models.CharField(verbose_name=_("Libellé niveau de formation ASP"), max_length=80)

    # TODO rme_id ???


class INSEECommune(PeriodMixin, CodeLabelMixin):
    """
    INSEE commune

    Code and name of French communes.
    Mainly used to get the commune code (different from postal code).

    Imported from ASP reference file: ref_insee_com_v1.csv

    Note:
    reference file is currently not up-to-date (2018)
    """

    code = models.CharField(max_length=5, verbose_name=_("Code commune INSEE"))
    name = models.CharField(max_length=50, verbose_name=_("Nom de la commune"))


class INSEEDepartment(PeriodMixin, CodeLabelMixin):
    """
    INSEE department code

    Code and name of French departments

    Imported from ASP reference file: ref_insee_dpt_v2.csv
    """

    code = models.CharField(max_length=3, verbose_name=_("Code département INSEE"))
    name = models.CharField(max_length=50, verbose_name=_("Nom du département"))


class INSEECountry(CodeLabelMixin):
    """
    INSEE country code

    Code and name of world countries

    Imported from ASP reference file: ref_insee_pays_v4.csv
    """

    class Group(models.TextChoices):
        FRANCE = "FRANCE", _("France")
        # FTR CEE = "Communauté Economique Européenne" is not used since 1993...
        CEE = "CEE", _("CEE")
        OUTSIDE_CEE = "OUTSIDE_CEE", _("Hors CEE")

    code = models.CharField(max_length=3, verbose_name=_("Code pays INSEE"))
    name = models.CharField(max_length=50, verbose_name=_("Nom du pays"))
    group = models.CharField(max_length=15, choices=Group.choices)
    # TODO DPT field ?

