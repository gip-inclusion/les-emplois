import re

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Lower, Replace
from django.utils import timezone
from django.utils.functional import cached_property, classproperty
from unidecode import unidecode

from itou.utils.models import DateRange, SlylyImmutableUnaccent


class LaneType(models.TextChoices):
    """
    Lane type

    Import/translation of ASP ref file: ref_type_voie_v3.csv
    """

    AER = "AER", "Aérodrome"
    AGL = "AGL", "Agglomération"
    AIRE = "AIRE", "Aire"
    ALL = "ALL", "Allée"
    ACH = "ACH", "Ancien chemin"
    ART = "ART", "Ancienne route"
    AV = "AV", "Avenue"
    BEGI = "BEGI", "Beguinage"
    BD = "BD", "Boulevard"
    BRG = "BRG", "Bourg"
    CPG = "CPG", "Camping"
    CAR = "CAR", "Carrefour"
    CTRE = "CTRE", "Centre"
    CCAL = "CCAL", "Centre commercial"
    CHT = "CHT", "Chateau"
    CHS = "CHS", "Chaussee"
    CHEM = "CHEM", "Chemin"
    CHV = "CHV", "Chemin vicinal"
    CITE = "CITE", "Cité"
    CLOS = "CLOS", "Clos"
    CTR = "CTR", "Contour"
    COR = "COR", "Corniche"
    COTE = "COTE", "Coteaux"
    COUR = "COUR", "Cour"
    CRS = "CRS", "Cours"
    DSC = "DSC", "Descente"
    DOM = "DOM", "Domaine"
    ECL = "ECL", "Ecluse"
    ESC = "ESC", "Escalier"
    ESPA = "ESPA", "Espace"
    ESP = "ESP", "Esplanade"
    FG = "FG", "Faubourg"
    FRM = "FRM", "Ferme"
    FON = "FON", "Fontaine"
    GAL = "GAL", "Galerie"
    GARE = "GARE", "Gare"
    GBD = "GBD", "Grand boulevard"
    GPL = "GPL", "Grande place"
    GR = "GR", "Grande rue"
    GRI = "GRI", "Grille"
    HAM = "HAM", "Hameau"
    IMM = "IMM", "Immeuble(s)"
    IMP = "IMP", "Impasse"
    JARD = "JARD", "Jardin"
    LD = "LD", "Lieu-dit"
    LOT = "LOT", "Lotissement"
    MAIL = "MAIL", "Mail"
    MAIS = "MAIS", "Maison"
    MAS = "MAS", "Mas"
    MTE = "MTE", "Montee"
    PARC = "PARC", "Parc"
    PRV = "PRV", "Parvis"
    PAS = "PAS", "Passage"
    PLE = "PLE", "Passerelle"
    PCH = "PCH", "Petit chemin"
    PRT = "PRT", "Petite route"
    PTR = "PTR", "Petite rue"
    PL = "PL", "Place"
    PTTE = "PTTE", "Placette"
    PLN = "PLN", "Plaine"
    PLAN = "PLAN", "Plan"
    PLT = "PLT", "Plateau"
    PONT = "PONT", "Pont"
    PORT = "PORT", "Port"
    PROM = "PROM", "Promenade"
    QUAI = "QUAI", "Quai"
    QUAR = "QUAR", "Quartier"
    RPE = "RPE", "Rampe"
    REMP = "REMP", "Rempart"
    RES = "RES", "Residence"
    ROC = "ROC", "Rocade"
    RPT = "RPT", "Rond-point"
    RTD = "RTD", "Rotonde"
    RTE = "RTE", "Route"
    RUE = "RUE", "Rue"
    RLE = "RLE", "Ruelle"
    SEN = "SEN", "Sente"
    SENT = "SENT", "Sentier"
    SQ = "SQ", "Square"
    TPL = "TPL", "Terre plein"
    TRAV = "TRAV", "Traverse"
    VEN = "VEN", "Venelle"
    VTE = "VTE", "Vieille route"
    VCHE = "VCHE", "Vieux chemin"
    VILL = "VILL", "Villa"
    VLGE = "VLGE", "Village"
    VOIE = "VOIE", "Voie"
    ZONE = "ZONE", "Zone"
    ZA = "ZA", "Zone d'activite"
    ZAC = "ZAC", "Zone d'amenagement concerte"
    ZAD = "ZAD", "Zone d'amenagement differe"
    ZI = "ZI", "Zone industrielle"
    ZUP = "ZUP", "Zone urbanisation prio"

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

    B = "B", "Bis"
    T = "T", "Ter"
    Q = "Q", "Quater"
    C = "C", "Quinquies"

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

    start_date = models.DateField(verbose_name="début de validité")
    end_date = models.DateField(verbose_name="fin de validité", null=True, blank=True)
    # AbstractPeriod objects also have a code, not present here but detailed in subclasses.

    objects = PeriodQuerySet.as_manager()

    class Meta:
        abstract = True
        constraints = [
            ExclusionConstraint(
                name="exclude_%(class)s_overlapping_dates",
                expressions=(
                    ("code", RangeOperators.EQUAL),
                    (
                        DateRange(
                            "start_date",
                            "end_date",
                            RangeBoundary(inclusive_lower=True, inclusive_upper=True),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ),
                violation_error_message="La période chevauche une autre période existante pour ce même code INSEE.",
            ),
        ]


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

    LESS_THAN_6_MONTHS = "01", "Moins de 6 mois"
    FROM_6_TO_11_MONTHS = "02", "De 6 à 11 mois"
    FROM_12_TO_23_MONTHS = "03", "De 12 à 23 mois"
    MORE_THAN_24_MONTHS = "04", "24 mois et plus"


class EducationLevel(models.TextChoices):
    """
    Education level of the employee

    In ASP reference file, education levels are linked with a "mesure" (ASP counterpart for SIAE kind)
    For a valid employee record, we only need to send the code.

    FTR: import file has incorrect field length for the code value (must be exactly 2 char.)

    Translation of ASP ref file: ref_niveau_formation_v3.csv
    """

    NON_CERTIFYING_QUALICATIONS = "00", "Personne avec qualifications non-certifiantes"
    NO_SCHOOLING = "01", "Jamais scolarisé"
    THIRD_CYCLE_OR_ENGINEERING_SCHOOL = "10", "Troisième cycle ou école d'ingénieur"
    LICENCE_LEVEL = "20", "Formation de niveau licence"
    BTS_OR_DUT_LEVEL = "30", "Formation de niveau BTS ou DUT"
    BAC_LEVEL = "40", "Formation de niveau BAC"
    BT_OR_BACPRO_LEVEL = "41", "Brevet de technicien ou baccalauréat professionnel"
    BEP_OR_CAP_LEVEL = "50", "Formation de niveau BEP ou CAP"
    BEP_OR_CAP_DIPLOMA = "51", "Diplôme obtenu CAP ou BEP"
    TRAINING_1_YEAR = "60", "Formation courte d'une durée d'un an"
    NO_SCHOOLING_BEYOND_MANDATORY = "70", "Pas de formation au-delà de la scolarité obligatoire"


class EmployerType(models.TextChoices):
    """
    Employer type

    Employer type codes aren't likely to change and ref file also have incorrect
    field length for 'code' (must be 2 char. and 0 left-padded)

    Translation of ASP ref file: ref_type_employeur_v3.csv
    """

    EI = "01", "Entreprise d'insertion"
    ETTI = "02", "Entreprise de travail temporaire d'insertion"
    AI = "03", "Association intermédiaire"
    ACI = "04", "Atelier chantier d'insertion"
    ESAT = "05", "Etablissement et service d'aide par le travail"
    EA = "06", "Entreprise adaptée"
    OTHER = "07", "Autre"

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

    Translation of ASP ref file: ref_orienteur_v5.csv
    """

    ML = "01", "Mission locale"
    CAP_EMPLOI = "02", "Cap emploi"
    FT = "03", "France Travail"
    PLIE = "04", "PLIE - Plan local pour l'insertion et l'emploi"
    DEPT = "05", "Service social du conseil départemental"
    OTHER_AUTHORIZED_PRESCRIBERS = "06", "Autre prescripteurs habilité"
    SPONTANEOUS_APPLICATION = "07", "Candidature spontanée"
    PRESCRIBERS = "08", "Orienteur (prescripteur non habilité)"
    SPIP = "09", "SPIP - Service pénitentiaire d'insertion et de probation"
    PJJ = "10", "PJJ - Protection judiciaire de la jeunesse"
    CCAS = "11", "CCAS - Centre (inter)communal d'action sociale"
    CHRS = "12", "CHRA - Centre d'hébergement et de réinsertion sociale"
    CIDFF = "13", "CIDFF - Centre d'information sur les droits des femmes et des familles"
    PREVENTION = "14", "Service ou club de prévention"
    AFPA = "15", "AFPA - Agence nationale pour la formation professionnelle des adultes"
    PIJ_BIJ = "16", "PIJ-BIJ - Point/Bureau information jeunesse"
    CAF = "17", "CAF - Caisse d'allocations familiales"
    CADA = "18", "CADA - Centre d'accueil de demandeurs d'asile"
    ASE = "19", "ASE - Aide sociale à l'enfance"
    CAVA = "20", "CAVA - Centre d'adaptation à la vie active"
    CPH = "21", "CPH - Centre provisoire d'hébergement"
    CHU = "22", "CHU - Centre d'hébergement d'urgence"
    OACAS = "23", "OACAS - Organisme d'accueil communautaire et d'activité solidaire"
    UNKNOWN = "99", "Non connu"


class CommuneQuerySet(PeriodQuerySet):
    def by_insee_code(self, insee_code: str):
        return self.all().current().filter(code=insee_code).get()

    def by_insee_code_and_period(self, insee_code, period):
        "Lookup a Commune object by INSEE code and valid at the given period"
        return (
            self.filter(code=insee_code, start_date__lte=period)
            .filter(Q(end_date=None) | Q(end_date__gte=period))
            .get()
        )


class UnfilteredCommuneManager(models.Manager.from_queryset(CommuneQuerySet)):
    use_in_migrations = True

    def get_queryset(self):
        return super().get_queryset()


class CommuneManager(models.Manager.from_queryset(CommuneQuerySet)):
    use_in_migrations = True

    def get_queryset(self):
        return super().get_queryset().exclude(ignore=True)


class Commune(PrettyPrintMixin, AbstractPeriod):
    """
    INSEE commune

    Code and name of French communes.
    Mainly used to get the commune code (different from postal code).

    Imported from ASP reference file: ref_insee_com_v2.
    Newer ones exists (ref_insee_com_v3, ref_insee_com_v4), but we don't use it yet as there are some discrepancies.

    Note:
    reference file is currently not up-to-date (2018)
    """

    code = models.CharField(max_length=5, verbose_name="code commune INSEE", db_index=True)
    name = models.CharField(max_length=50, verbose_name="nom de la commune")

    normalized_name = models.GeneratedField(
        expression=Replace(Lower(SlylyImmutableUnaccent("name")), Value("-"), Value(" ")),
        output_field=models.CharField(),
        verbose_name="nom normalisé pour faciliter la recherche",
        db_persist=True,
    )

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    # A corresponding INSEE City is associated in order to also get the current display name and post codes.
    # Our research concluded that with the latest (December 2022) ASP reference file,
    # - All the INSEE cities have a corresponding ASP commune
    # - Some "active" ASP communes don't have a corresponding INSEE city; when we check, the INSEE city is "inactive"
    #   which means that there has been some changes on the INSEE side since.
    # What does it mean ? When we autocomplete for an address on the BAN, in 100% of the cases we'll have
    # an INSEE City, thus an ASP Commune and it can be safely used for the employee records.
    city = models.ForeignKey("cities.City", on_delete=models.SET_NULL, verbose_name="ville INSEE", null=True)
    ignore = models.BooleanField(verbose_name="commune désactivée", default=False, db_default=False)

    objects = CommuneManager()
    unfiltered_objects = UnfilteredCommuneManager()

    class Meta(AbstractPeriod.Meta):
        verbose_name = "commune"
        indexes = [
            GinIndex(fields=["normalized_name"], name="%(class)s_normalized_name_gin", opclasses=["gin_trgm_ops"])
        ]

    @cached_property
    def department_code(self):
        """
        INSEE department code are the first 2 characters of the commune code

        For processing concerns, ASP expects 3 characters: 0-padding is the way
        except for department code beginning with 97 or 98 ("Outremer")
        """
        if self.code.startswith("97") or self.code.startswith("98"):
            return self.code[0:3]

        # But in most of the cases:
        return f"0{self.code[0:2]}"

    def autocomplete_display(self):
        return f"{self.name} ({self.department_code})"


class Department(PrettyPrintMixin, AbstractPeriod):
    """
    INSEE department code

    Code and name of French departments

    Imported from ASP reference file: ref_insee_dpt_v2.csv
    """

    code = models.CharField(max_length=3, verbose_name="code département INSEE")
    name = models.CharField(max_length=50, verbose_name="nom du département")

    class Meta(AbstractPeriod.Meta):
        verbose_name = "département"


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

    Imported from ASP reference file: ref_grp_pays_v1, ref_insee_pays_v4.csv
    """

    INSEE_CODE_FRANCE = "100"
    _ID_FRANCE = None

    class Group(models.TextChoices):
        FRANCE = "1", "France"
        # FTR CEE = "Communauté Economique Européenne" and is not used since 1993...
        CEE = "2", "CEE"
        OUTSIDE_CEE = "3", "Hors CEE"

    objects = CountryQuerySet.as_manager()

    code = models.CharField(max_length=3, verbose_name="code pays INSEE")
    name = models.CharField(max_length=50, verbose_name="nom du pays")
    group = models.CharField(max_length=15, verbose_name="groupe", choices=Group.choices)

    # For compatibility, no usage yet
    department = models.CharField(max_length=3, verbose_name="code département", default="098")

    class Meta:
        verbose_name = "pays"
        verbose_name_plural = "pays"
        ordering = ["name"]

    @classproperty
    def france_id(cls):
        if cls._ID_FRANCE is None:
            cls._ID_FRANCE = Country.objects.get(code=Country.INSEE_CODE_FRANCE).pk
        return cls._ID_FRANCE


class SiaeMeasure(models.TextChoices):
    """
    ASP SIAE kind (mesure)

    ASP Equivalent to Siae.Kind, but codes are different

    Was previously a Django model, but overkill.
    We only need a subset of the available codes.
    """

    ACI = "ACI_DC", "Droit Commun - Atelier et Chantier d'Insertion"
    AI = "AI_DC", "Droit Commun - Association Intermédiaire"
    EI = "EI_DC", "Droit Commun -  Entreprise d'Insertion"
    EITI = "EITI_DC", "Droit Commun - Entreprise d'Insertion par le Travail Indépendant"
    ETTI = "ETTI_DC", "Droit Commun - Entreprise de Travail Temporaire d'Insertion"

    # These codes are currently not used at Itou
    ACI_MP = "ACI_MP", "Milieu Pénitentiaire - Atelier et Chantier d'Insertion"
    EI_MP = "EI_MP", "Milieu Pénitentiaire - Entreprise d'Insertion"
    FDI = "FDI_DC", "Droit Commun -  Fonds Départemental pour l'Insertion"

    @classmethod
    def from_siae_kind(cls, kind):
        """
        Mapping between Itou SIAE kinds and ASP "Mesures"
        """
        kinds = {
            "ACI": cls.ACI,
            "AI": cls.AI,
            "EI": cls.EI,
            "EITI": cls.EITI,
            "ETTI": cls.ETTI,
        }
        # No fallback (None)
        return kinds.get(kind)


class RSAAllocation(models.TextChoices):
    """
    An employee can benefit from RSA allowance:
    = with or without ("Majoré" and "Non-Majoré")
    - or not at all

    => There are 3 distinct cases for an answer.
    """

    NO = "NON", "Non bénéficiaire du RSA"
    YES_WITH_MARKUP = "OUI-M", "Bénéficiaire du RSA et majoré"
    YES_WITHOUT_MARKUP = "OUI-NM", "Bénéficiaire du RSA et non-majoré"


class EITIContributions(models.TextChoices):
    RETAIL = "01", "Achat/revente de marchandises"
    TRADE_AND_CRAFT_SERVICES = "02", "Prestations de services commerciales et artisanales"
    OTHER_SERVICES = "03", "Autres prestations de services"
    REGULATED_CIPAV = "04", "Professions libérales règlementées relevant de la Cipav"
    FURNISHED_ACCOMMODATION_RENTAL = "05", "Locations de meublés de tourisme classés"
    UNDETERMINED = "06", "Non déterminé (contrat établi avant 2025)"
