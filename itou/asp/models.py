import re
from enum import Enum

from django.db import models
from django.utils.translation import gettext_lazy as _
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
    """
    Alternative lookup of some lane types.
    Help improving overall quality of ASP address formatting
    """
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


class PeriodQuerySet(models.QuerySet):
    def current(self):
        """
        Return all currently valid objects, i.e.:
        - currently usable as a reference for new objects
        - their end date must be None (active / non-historized entry)

        As with all reference files from ASP, we do not alter or summarize their content
        when importing or reshaping them.
        Even more with elements with effective dates (start / end / history concerns).
        """
        return self.filter(end_date=None)

    def old(self):
        """
        Return "old" objects <=> objects with an end_date,
        These objects can't be used for new employee records (hence "old" entries)
        """
        return self.exclude(end_date=None)


class AbstractPeriod(models.Model):
    """
    Abstract for reference files having history concerns (start_date and end_date defined)

    - 'type.objects.old' is a QS with ALL previous versions of a record
    - 'type.objects.current' is a QS returning ONLY valid records for current date / version subset

    => Use 'current' for most use cases.
    => Use 'old' when you have to deal with history or previous version of a record
    """

    start_date = models.DateField(verbose_name=_("Début de validité"))
    end_date = models.DateField(verbose_name=_("Fin de validité"), null=True)

    objects = models.Manager.from_queryset(PeriodQuerySet)()

    class Meta:
        abstract = True


class PrettyPrintMixin:
    def __str__(self):
        return self.name

    def __repr__(self):
        return f"{type(self).__name__}: pk={self.pk}, code={self.code}"


class AllocationDuration(models.TextChoices):
    """
    Translation of ASP ref file: ref_duree_allocation_emploi_v2.csv

    Note: effect periods are not handled
    """

    LESS_THAN_6_MONTHS = "LESS_THAN_6_MONTHS", _("Moins de 6 mois")
    FROM_6_TO_11_MONTHS = "FROM_6_TO_11_MONTHS", _("De 6 à 11 mois")
    FROM_12_TO_23_MONTHS = "FROM_12_TO_23_MONTHS", _("De 12 à 23 mois")
    MORE_THAN_24_MONTHS = "MORE_THAN_24_MONTHS", _("24 mois et plus")


class EducationLevel(models.TextChoices):
    """
    Education level of the employee

    In ASP reference file, education levels are linked with a "mesure" (ASP counterpart for SIAE kind)
    For a valid employee record, we only need to send the code.

    FTR: import file has incorrect field length for the code value (must be exactly 2 char.)

    Translation of ASP ref file: ref_niveau_formation_v3.csv
    """

    NON_CERTIFIING_QUALICATIONS = "00", _("Personne avec qualifications non-certifiantes")
    NO_SCHOOLING = "01", _("Jamais scolarisé")
    THIRD_CYCLE_OR_ENGINEERING_SCHOOL = "10", _("Troisième cycle ou écolde d'ingénieur")
    LICENCE_LEVEL = "20", _("Formation de niveau licence")
    BTS_OR_DUT_LEVEL = "30", _("Formation de niveau BTS ou DUT")
    BAC_LEVEL = "40", _("Formation de niveau BAC")
    BT_OR_BACPRO_LEVEL = "41", _("Brevet de technicien ou baccalauréat professionnel")
    BEP_OR_CAP_LEVEL = "50", _("Formation de niveau BEP ou CAP")
    BEP_OR_CAP_DIPLOMA = "51", _("Diplôme obtenu CAP ou BEP")
    TRAINING_1_YEAR = "60", _("Formation courte d'une durée d'un an")
    NO_SHOOLING_BEYOND_MANDATORY = "70", _("Pas de formation au-delà de la scolarité obligatoire")


class Commune(PrettyPrintMixin, AbstractPeriod):
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

    class Meta:
        verbose_name = _("Commune")


class Department(PrettyPrintMixin, AbstractPeriod):
    """
    INSEE department code

    Code and name of French departments

    Imported from ASP reference file: ref_insee_dpt_v2.csv
    """

    code = models.CharField(max_length=3, verbose_name=_("Code département INSEE"))
    name = models.CharField(max_length=50, verbose_name=_("Nom du département"))

    class Meta:
        verbose_name = _("Département")


class Country(PrettyPrintMixin, models.Model):
    """
    INSEE country code

    Code and name of world countries

    Imported from ASP reference file: ref_insee_pays_v4.csv
    """

    class Group(models.TextChoices):
        FRANCE = "1", _("France")
        # FTR CEE = "Communauté Economique Européenne" and is not used since 1993...
        CEE = "2", _("CEE")
        OUTSIDE_CEE = "3", _("Hors CEE")

    code = models.CharField(max_length=3, verbose_name=_("Code pays INSEE"))
    name = models.CharField(max_length=50, verbose_name=_("Nom du pays"))
    group = models.CharField(max_length=15, choices=Group.choices)

    # For compatibility, no usage yet
    department = models.CharField(max_length=3, verbose_name=_("Code département"), default="098")

    class Meta:
        verbose_name = _("Pays")
        verbose_name_plural = _("Pays")


class SiaeKind(PrettyPrintMixin, AbstractPeriod):
    """
    ASP SIAE kind (mesure)

    ASP Equivalent to Siae.Kind, but codes are different
    """

    # Field code and display code are inverted for current usage, so:
    # - 'Measure.code' is 'Rme_code_mesure_disp' ASP field
    # - 'Measure.display_code' is 'Rme_code_mesure'
    # - 'help_code' is 'Rme_code_aide'
    code = models.CharField(max_length=10, verbose_name=_("Code mesure ASP complet"))
    display_code = models.CharField(max_length=5, verbose_name=_("Code mesure ASP resumé"))
    help_code = models.CharField(max_length=5, verbose_name=_("Code d'aide mesure ASP"))
    name = models.CharField(max_length=80, verbose_name=_("Libellé mesure ASP"))

    # I don't know what this ID is about yet, seems unused but kept for compatibility
    rdi_id = models.CharField(max_length=1, verbose_name=_("Identifiant RDI ?"))

    class Meta:
        verbose_name = _("Mesure")
