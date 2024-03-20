import logging

from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.postgres.search import TrigramSimilarity
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.template.defaultfilters import slugify
from django.utils import timezone
from django.utils.functional import cached_property

from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, REGIONS, department_from_postcode
from itou.geo.models import QPV, ZRR
from itou.utils.apis.exceptions import AddressLookupError, GeocodingDataError
from itou.utils.apis.geocoding import batch as batch_geocode, get_geocoding_data
from itou.utils.validators import validate_post_code


logger = logging.getLogger(__name__)

# this score assures us almost zero false positives, after careful semi-manual inspection.
# see the comments on BAN_API_LEGACY_RELIANCE_SCORE below for more details.
# there is ample discussion about this topic in our Notion.
BAN_API_RELIANCE_SCORE = 0.8


class ArrayLength(models.Func):
    function = "CARDINALITY"


def lat_lon_to_coords(lat, lon):
    if lat is not None and lon is not None:
        return GEOSGeometry(f"POINT({lon} {lat})")
    return None


def resolve_insee_city(city_name, post_code):
    if not city_name or not post_code:
        return None
    cities = (
        City.objects.annotate(similarity=TrigramSimilarity("name", city_name))
        .filter(post_codes__contains=[post_code])
        .annotate(post_code_length=ArrayLength("post_codes"))
        # 30% of matching trigrams match seemed enough in our tests.
        .filter(similarity__gt=0.3)
        # First sort by trigram similarity; if equal (Paris, 75008 matches Paris and Paris 8)
        # then minimal post code list is going to be the most specific.
        .order_by("-similarity", "post_code_length")
    )
    if cities:
        return cities[0]
    return None


def geolocate_qs(qs, is_verbose=False):
    now = timezone.now()

    non_geolocated_qs = qs.filter(
        Q(coords__isnull=True) | Q(geocoding_score__isnull=True) | Q(geocoding_score__lt=BAN_API_RELIANCE_SCORE)
    )

    if is_verbose:
        print(
            f"> about to geolocate count={non_geolocated_qs.count()} objects "
            "without geolocation or with a low score."
        )

    # Note : we could also order by latest geolocalization attempt. An order is necessary though
    # for the zip() to work correctly later.
    localizable_qs = non_geolocated_qs.exclude(Q(address_line_1="") | Q(post_code="")).order_by("pk")

    if is_verbose:
        print(f"> count={localizable_qs.count()} of these have an address and a post code.")

    for obj, geo_result in zip(
        localizable_qs, batch_geocode(localizable_qs.values("pk", "address_line_1", "post_code"))
    ):
        score = float(geo_result["result_score"] or 0.0)
        if is_verbose:
            print(
                f"API result score={geo_result['result_score'] or 0.0} "
                f"label='{geo_result['result_label'] or 'unknown'}' "
                f"searched_address='{obj.address_line_1} {obj.post_code}' object_pk={obj.pk}"
            )
        if score >= BAN_API_RELIANCE_SCORE:
            if obj.geocoding_score and obj.geocoding_score > score:  # do not yield lower scores than the current
                continue
            obj.coords = lat_lon_to_coords(geo_result["latitude"], geo_result["longitude"])
            obj.geocoding_score = score
            obj.ban_api_resolved_address = geo_result["result_label"]
            obj.geocoding_updated_at = now
            yield obj


class AddressMixin(models.Model):
    """
    Designing an Address model is tricky.
    So let's just keep it as simple as possible.
    We'll use a parser if the need arises.

    Some reading on the subject.
    https://www.mjt.me.uk/posts/falsehoods-programmers-believe-about-addresses/
    https://machinelearnings.co/statistical-nlp-on-openstreetmap-b9d573e6cc86
    https://github.com/openvenues/libpostal
    https://github.com/openvenues/pypostal

    Assume that all addresses are in France. This is unlikely to change.
    """

    # Below this score, results from `adresse.data.gouv.fr` are considered unreliable.
    # This score is arbitrarily set based on general observation.
    #
    # Technically this score is mainly a string distance between the model's address and the API-returned one.
    # https://github.com/addok/addok/blob/master/docs/faq.md#how-is-the-score-computed
    #
    # A bit of history: this score was originally set at 0.6 (so, more or less 60% of characters matching)
    # and has been lowered in 2019 to 0.4, mentioning that it was good enough.
    #
    # At the time of writing, this score is used in 3 places:
    # - MOSTLY in the search: SIAEs and prescriber organizations are located through their coordinates.
    # - the dashboard, to force SIAE or prescriber admins to go re-locate their structure;
    # - in the _import_siae script, to get better looking addresses for the SIAEs if the API result is above that score
    #
    # In all cases, the use of this threshold is disputable since we can get incorrect results even with a
    # high score ("rue des Clous" vs "rue des Cloÿs" is above 0.4) if the user can't double check it visually.
    #
    # After a bit more of a quantitative investigation, it seems that up to 85% of the SIAEs would have a score
    # above 0.8, and 93.5% above 0.6. Upping this threshold would make:
    # - to 0.6, 482 SIAEs have to update their coords (10x more than today)
    # - to 0.8, 1109 SIAEs have to update their address (22x more than today)
    # but that would enable having the same reliance score for everyone.
    #
    # On the longer term, since there is no way to be certain that the API address matches the user's intent we should
    # instead implement a way for the user to confirm it directly (semi-auto selection in the form for instance)
    BAN_API_LEGACY_RELIANCE_SCORE = 0.4

    DEPARTMENT_CHOICES = DEPARTMENTS.items()

    address_line_1 = models.CharField(verbose_name="adresse", max_length=255, blank=True)
    address_line_2 = models.CharField(
        verbose_name="complément d'adresse",
        max_length=255,
        blank=True,
        help_text="Appartement, suite, bloc, bâtiment, boite postale, etc.",
    )
    post_code = models.CharField(
        verbose_name="code postal",
        validators=[validate_post_code],
        max_length=5,
        blank=True,
    )
    city = models.CharField(verbose_name="ville", max_length=255, blank=True)
    department = models.CharField(
        verbose_name="département",
        choices=DEPARTMENT_CHOICES,
        max_length=3,
        blank=True,
        db_index=True,
    )
    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True, null=True, blank=True)
    # BAN API score between 0 and 1 indicating the relevance of the geocoding result.
    geocoding_score = models.FloatField(verbose_name="score du geocoding", blank=True, null=True)
    geocoding_updated_at = models.DateTimeField(
        verbose_name="dernière modification du geocoding",
        blank=True,
        null=True,
    )
    ban_api_resolved_address = models.TextField(
        verbose_name="libellé d'adresse retourné par le dernier geocoding",
        blank=True,
        null=True,
    )

    insee_city = models.ForeignKey("cities.City", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        abstract = True

    @property
    def latitude(self):
        if self.coords:
            return self.coords.y
        return None

    @property
    def longitude(self):
        if self.coords:
            return self.coords.x
        return None

    @property
    def region(self):
        if self.department:
            for region, departments in REGIONS.items():
                if self.department in departments:
                    return region
        return None

    @property
    def has_reliable_coords_legacy(self):
        if not self.geocoding_score:
            return False
        return self.geocoding_score >= self.BAN_API_LEGACY_RELIANCE_SCORE

    @property
    def address_on_one_line(self):
        if not all([self.address_line_1, self.post_code, self.city]):
            return None
        fields = [
            self.address_line_1,
            self.address_line_2,
            f"{self.post_code} {self.city}",
        ]
        return ", ".join([field for field in fields if field])

    @property
    def geocoding_address(self):
        """
        Using `address_on_one_line` field for geocoding can lead to poor scores
        (because of `address_line_2` field).
        - use `address_on_one_line` for display
        - use `geocoding_address` for geocoding process
        """
        if not all([self.address_line_1, self.post_code, self.city]):
            return None
        fields = [self.address_line_1, f"{self.post_code} {self.city}"]
        return ", ".join([field for field in fields if field])

    @property
    def city_slug(self):
        """For cities.city matching / search"""
        return slugify(f"{self.city}-{self.department}")

    @cached_property
    def address_in_qpv(self):
        try:
            if QPV.in_qpv(self, geom_field="coords"):
                return self.address_on_one_line
        except ValueError as ex:
            logger.warning(f"Unable to detect QPV: {ex}")
        return None

    @cached_property
    def zrr_city_name(self):
        try:
            # Avoid circular import
            from itou.cities.models import City

            # There's currently no direct link between User.city and Cities.City
            city = City.objects.get(slug=self.city_slug)
        except City.DoesNotExist:
            logger.warning(f"Can't match INSEE code:  city '{self.city}' has no match in 'Cities.City' model")
        else:
            if ZRR.objects.in_zrr().filter(insee_code=city.code_insee):
                return city.name, False
            elif ZRR.objects.partially_in_zrr().filter(insee_code=city.code_insee):
                return city.name, True
        return None

    def set_coords(self):
        try:
            geocoding_data = get_geocoding_data(self.geocoding_address, post_code=self.post_code)
        except GeocodingDataError as exc:
            # The coordinates are not erased because they are used in the search engine,
            # even if they no longer correspond to the address.
            logger.error("No geocoding data could be found for `%s - %s`", self.geocoding_address, self.post_code)
            raise AddressLookupError(
                f"L'adresse '{self.geocoding_address}' - {self.post_code}"
                " n'a pas été trouvée dans la Base Adresse Nationale."
            ) from exc
        else:
            self.coords = geocoding_data["coords"]
            self.geocoding_score = geocoding_data["score"]

    def clean(self):
        if self.department != department_from_postcode(self.post_code):
            raise ValidationError("Le département doit correspondre au code postal.")

        super().clean()
