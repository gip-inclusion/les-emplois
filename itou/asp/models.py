import re

from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from unidecode import unidecode


class LaneType(models.TextChoices):
    """
    Lane type

    Import/translation of ASP ref file: ref_type_voie_v3.csv
    """

    AER = "AER", _("Aérodrome")
    AGL = "AGL", _("Agglomération")
    AIRE = "AIRE", _("Aire")
    ALL = "ALL", _("Allée")
    ACH = "ACH", _("Ancien chemin")
    ART = "ART", _("Ancienne route")
    AV = "AV", _("Avenue")
    BEGI = "BEGI", _("Beguinage")
    BD = "BD", _("Boulevard")
    BRG = "BRG", _("Bourg")
    CPG = "CPG", _("Camping")
    CAR = "CAR", _("Carrefour")
    CTRE = "CTRE", _("Centre")
    CCAL = "CCAL", _("Centre commercial")
    CHT = "CHT", _("Chateau")
    CHS = "CHS", _("Chaussee")
    CHEM = "CHEM", _("Chemin")
    CHV = "CHV", _("Chemin vicinal")
    CITE = "CITE", _("Cité")
    CLOS = "CLOS", _("Clos")
    CTR = "CTR", _("Contour")
    COR = "COR", _("Corniche")
    COTE = "COTE", _("Coteaux")
    COUR = "COUR", _("Cour")
    CRS = "CRS", _("Cours")
    DSC = "DSC", _("Descente")
    DOM = "DOM", _("Domaine")
    ECL = "ECL", _("Ecluse")
    ESC = "ESC", _("Escalier")
    ESPA = "ESPA", _("Espace")
    ESP = "ESP", _("Esplanade")
    FG = "FG", _("Faubourg")
    FRM = "FRM", _("Ferme")
    FON = "FON", _("Fontaine")
    GAL = "GAL", _("Galerie")
    GARE = "GARE", _("Gare")
    GBD = "GBD", _("Grand boulevard")
    GPL = "GPL", _("Grande place")
    GR = "GR", _("Grande rue")
    GRI = "GRI", _("Grille")
    HAM = "HAM", _("Hameau")
    IMM = "IMM", _("Immeuble(s)")
    IMP = "IMP", _("Impasse")
    JARD = "JARD", _("Jardin")
    LD = "LD", _("Lieu-dit")
    LOT = "LOT", _("Lotissement")
    MAIL = "MAIL", _("Mail")
    MAIS = "MAIS", _("Maison")
    MAS = "MAS", _("Mas")
    MTE = "MTE", _("Montee")
    PARC = "PARC", _("Parc")
    PRV = "PRV", _("Parvis")
    PAS = "PAS", _("Passage")
    PLE = "PLE", _("Passerelle")
    PCH = "PCH", _("Petit chemin")
    PRT = "PRT", _("Petite route")
    PTR = "PTR", _("Petite rue")
    PL = "PL", _("Place")
    PTTE = "PTTE", _("Placette")
    PLN = "PLN", _("Plaine")
    PLAN = "PLAN", _("Plan")
    PLT = "PLT", _("Plateau")
    PONT = "PONT", _("Pont")
    PORT = "PORT", _("Port")
    PROM = "PROM", _("Promenade")
    QUAI = "QUAI", _("Quai")
    QUAR = "QUAR", _("Quartier")
    RPE = "RPE", _("Rampe")
    REMP = "REMP", _("Rempart")
    RES = "RES", _("Residence")
    ROC = "ROC", _("Rocade")
    RPT = "RPT", _("Rond-point")
    RTD = "RTD", _("Rotonde")
    RTE = "RTE", _("Route")
    RUE = "RUE", _("Rue")
    RLE = "RLE", _("Ruelle")
    SEN = "SEN", _("Sente")
    SENT = "SENT", _("Sentier")
    SQ = "SQ", _("Square")
    TPL = "TPL", _("Terre plein")
    TRAV = "TRAV", _("Traverse")
    VEN = "VEN", _("Venelle")
    VTE = "VTE", _("Vieille route")
    VCHE = "VCHE", _("Vieux chemin")
    VILL = "VILL", _("Villa")
    VLGE = "VLGE", _("Village")
    VOIE = "VOIE", _("Voie")
    ZONE = "ZONE", _("Zone")
    ZA = "ZA", _("Zone d'activite")
    ZAC = "ZAC", _("Zone d'amenagement concerte")
    ZAD = "ZAD", _("Zone d'amenagement differe")
    ZI = "ZI", _("Zone industrielle")
    ZUP = "ZUP", _("Zone urbanisation prio")

    @classmethod
    def with_similar_name(cls, name):
        "Returns enum with similar name"
        return cls.__members__.get(name.upper())

    @classmethod
    def with_similar_value(cls, value):
        "Returns enum with a similar value"
        revert_map = {unidecode(lt.label.lower()): lt for lt in cls}
        return revert_map.get(value.lower())


# Even if geo API does a great deal of a job,
# it sometimes shows unexpected result labels for lane types
# like 'r' for 'rue', or 'Av' for 'Avenue', etc.
# This a still incomplete mapping of these variations
_LANE_TYPE_ALIASES = {
    "^r": LaneType.RUE,
    "^che": LaneType.CHEM,
    "^grande?[ -]rue": LaneType.GR,
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


class LaneExtension(models.TextChoices):
    """
    Lane extension

    Import/translation of ASP ref file: ref_extension_voie_v1.csv
    """

    B = "B", _("Bis")
    T = "T", _("Ter")
    Q = "Q", _("Quater")
    C = "C", _("Quinquies")

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

    LESS_THAN_6_MONTHS = "01", _("Moins de 6 mois")
    FROM_6_TO_11_MONTHS = "02", _("De 6 à 11 mois")
    FROM_12_TO_23_MONTHS = "03", _("De 12 à 23 mois")
    MORE_THAN_24_MONTHS = "04", _("24 mois et plus")


class EducationLevel(models.TextChoices):
    """
    Education level of the employee

    In ASP reference file, education levels are linked with a "mesure" (ASP counterpart for SIAE kind)
    For a valid employee record, we only need to send the code.

    FTR: import file has incorrect field length for the code value (must be exactly 2 char.)

    Translation of ASP ref file: ref_niveau_formation_v3.csv
    """

    NON_CERTIFYING_QUALICATIONS = "00", _("Personne avec qualifications non-certifiantes")
    NO_SCHOOLING = "01", _("Jamais scolarisé")
    THIRD_CYCLE_OR_ENGINEERING_SCHOOL = "10", _("Troisième cycle ou école d'ingénieur")
    LICENCE_LEVEL = "20", _("Formation de niveau licence")
    BTS_OR_DUT_LEVEL = "30", _("Formation de niveau BTS ou DUT")
    BAC_LEVEL = "40", _("Formation de niveau BAC")
    BT_OR_BACPRO_LEVEL = "41", _("Brevet de technicien ou baccalauréat professionnel")
    BEP_OR_CAP_LEVEL = "50", _("Formation de niveau BEP ou CAP")
    BEP_OR_CAP_DIPLOMA = "51", _("Diplôme obtenu CAP ou BEP")
    TRAINING_1_YEAR = "60", _("Formation courte d'une durée d'un an")
    NO_SCHOOLING_BEYOND_MANDATORY = "70", _("Pas de formation au-delà de la scolarité obligatoire")


class EmployerType(models.TextChoices):
    """
    Employer type

    Employer type codes aren't likely to change and ref file also have incorrect
    field length for 'code' (must be 2 char. and 0 left-padded)

    Translation of ASP ref file: ref_type_employeur_v3.csv
    """

    EI = "01", _("Entreprise d'insertion")
    ETTI = "02", _("Entreprise de travail temporaire d'insertion")
    AI = "03", _("Association intermédiaire")
    ACI = "04", _("Atelier chantier d'insertion")
    ESAT = "05", _("Etablissement et service d'aide par le travail")
    EA = "06", _("Entreprise adaptée")
    OTHER = "07", _("Autre")

    @classmethod
    def from_itou_siae_kind(cls, siae_kind):
        """
        Mapping for ITOU employer type

        Mapping with litteral ITOU value (unlikely to change)
        to avoid unnecessary import of Siae.

        No mapping yet for ESAT
        """
        if siae_kind == "EI":
            return cls.EI
        elif siae_kind == "ETTI":
            return cls.ETTI
        elif siae_kind == "AI":
            return cls.AI
        elif siae_kind == "ACI":
            return cls.ACI
        elif siae_kind == "EA":
            return cls.EA

        return cls.OTHER


class PrescriberType(models.TextChoices):
    """
    Prescriber type

    Mapping between ASP and Itou prescriber types

    Prescriber (ASP "Orienteur") types are:
    - dispatched by "Mesure" (ASP SIAE kind)
    - not likely to change

    So they can be summarized as a simple list of text choices.

    Similar to EmployerType above, and with the same padding issue
    """

    ML = "01", _("Mission locale")
    CAP_EMPLOI = "02", _("CAP emploi")
    PE = "03", _("Pôle emploi")
    PLIE = "04", _("Plan local pour l'insertion et l'emploi")
    DEPT = "05", _("Service départementaux")
    AUTHORIZED_PRESCRIBERS = "06", _("Prescripteurs habilités")
    SPONTANEOUS_APPLICATION = "07", _("Candidature spontanée")
    UNKNOWN = "99", _("Non connu")

    @classmethod
    def from_itou_prescriber_kind(cls, prescriber_kind):
        if prescriber_kind == "ML":
            return cls.ML
        elif prescriber_kind == "CAP_EMPLOI":
            return cls.CAP_EMPLOI
        elif prescriber_kind == "PE":
            return cls.PE
        elif prescriber_kind == "PLIE":
            return cls.PLIE
        elif prescriber_kind == "DEPT":
            return cls.DEPT

        return cls.UNKNOWN


class CommuneManager(models.Manager):
    def get_queryset(self):
        return PeriodQuerySet(self.model)

    def by_insee_code(self, insee_code):
        """
        Lookup a Commune by INSEE code

        May return several results if not used with PeriodQuerySet.current
        """
        return self.get_queryset().filter(code=insee_code).first()


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

    objects = CommuneManager()

    class Meta:
        verbose_name = _("Commune")

    @cached_property
    def department_code(self):
        """
        INSEE department code are the first 2 characters of the commune code
        With no exception.

        For processing concerns, ASP expects 3 characters: 0-padding is the way
        """
        return f"0{self.code[0:2]}"


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


class CountryQuerySet(models.QuerySet):
    def france(self):
        return self.filter(group=Country.Group.FRANCE)

    def europe(self):
        return self.filter(group=Country.Group.CEE)

    def outside_europe(self):
        return self.filter(group=Country.Group.OUTSIDE_CEE)


class Country(PrettyPrintMixin, models.Model):
    """
    INSEE country code

    Code and name of world countries

    Imported from ASP reference file: ref_insee_pays_v4.csv
    """

    _CODE_FRANCE = "100"

    class Group(models.TextChoices):
        FRANCE = "1", _("France")
        # FTR CEE = "Communauté Economique Européenne" and is not used since 1993...
        CEE = "2", _("CEE")
        OUTSIDE_CEE = "3", _("Hors CEE")

    objects = models.Manager.from_queryset(CountryQuerySet)()

    code = models.CharField(max_length=3, verbose_name=_("Code pays INSEE"))
    name = models.CharField(max_length=50, verbose_name=_("Nom du pays"))
    group = models.CharField(max_length=15, verbose_name=_("Groupe"), choices=Group.choices)

    # For compatibility, no usage yet
    department = models.CharField(max_length=3, verbose_name=_("Code département"), default="098")

    class Meta:
        verbose_name = _("Pays")
        verbose_name_plural = _("Pays")

    @cached_property
    def is_france(self):
        """
        Check if provided country is France
        Polynesian islands are considered as a disting country but are french in fine
        """
        return self.group == self.Group.FRANCE


class SiaeKind(models.TextChoices):
    """
    ASP SIAE kind (mesure)

    ASP Equivalent to Siae.Kind, but codes are different

    Was previously a Django model, but overkill.
    We only need a subset of the available codes.
    """

    AI = "AI_DC", _("Droit Commun - Association Intermédiaire")
    ACI = "ACI_DC", _("Droit Commun - Atelier et Chantier d'Insertion")
    EI = "EI_DC", _("Droit Commun -  Entreprise d'Insertion")
    ETTI = "ETTI_DC", _("Droit Commun -  Entreprise de Travail Temporaire d'Insertion")
    EITI = "EITI_DC", _("Entreprise d'Insertion par le Travail Indépendant")

    # These codes are currently not used at Itou
    FDI = "FDI_DC", _("Droit Commun -  Fonds Départemental pour l'Insertion")
    EI_MP = "EI_MP", _("Milieu Pénitentiaire - Entreprise d'Insertion")
    ACI_MP = "ACI_MP", _("Milieu Pénitentiaire - Atelier et Chantier d'Insertion")

    @cached_property
    def valid_kind_for_employee_record(self):
        """
        The ASP SIAE kind ("Mesure") must be one of the following
        to be eligible for ASP employee record processing
        """
        return self.value in ["AI_DC", "ACI_DC", "ETTI_DC", "EI_DC"]

    @classmethod
    def from_siae_kind(cls, kind):
        """
        Mapping between Itou SIAE kinds and ASP "Mesures"
        """
        if kind == "AI":
            return cls.AI
        if kind == "ACI":
            return cls.ACI
        if kind == "EI":
            return cls.EI
        if kind == "ETTI":
            return cls.ETTI
        if kind == "EITI":
            return cls.EITI

        # No mapping in ASP
        return None
