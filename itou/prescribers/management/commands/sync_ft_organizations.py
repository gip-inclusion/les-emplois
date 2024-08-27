from django.db import IntegrityError, transaction
from django.db.models import Q

from itou.cities.models import City
from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE, lat_lon_to_coords
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.utils.apis import pole_emploi_api_client
from itou.utils.command import BaseCommand
from itou.utils.sync import DiffItemKind, yield_sync_diff


def name_from_api_data(data):
    # Sometimes the `libelle` field can start with a "*",
    # it's most likely linked to the alias that agents can use instead of the official APE's email.
    return f'France Travail - {data["libelle"].lstrip("*")}'


def phone_from_api_data(data):
    return data.get("contact", {}).get("telephonePublic", "")


def email_from_api_data(data):
    return data.get("contact", {}).get("email", "")


def address_from_api_data(data):
    return data["adressePrincipale"].get("ligne4")


def address_extra_from_api_data(data):
    return data["adressePrincipale"].get("ligne3", "")


def post_code_from_api_data(data):
    return data["adressePrincipale"].get("bureauDistributeur")


def coordinates_from_api_data(data):
    return lat_lon_to_coords(data["adressePrincipale"].get("gpsLat"), data["adressePrincipale"].get("gpsLon"))


def insee_city_from_api_data(data):
    try:
        return City.objects.get(code_insee=data["adressePrincipale"].get("communeImplantation"))
    except City.DoesNotExist:
        return None


def fill_organization_from_api_data(obj, siret, data):
    # Basic information
    obj.siret = siret
    obj.name = name_from_api_data(data)
    # Contact information
    obj.phone = phone_from_api_data(data)
    obj.email = email_from_api_data(data)
    # Address
    obj.address_line_1 = address_from_api_data(data)
    obj.address_line_2 = address_extra_from_api_data(data)
    obj.post_code = post_code_from_api_data(data)
    # Geolocation
    obj.coords = coordinates_from_api_data(data)
    obj.geocoding_score = BAN_API_RELIANCE_SCORE if obj.coords else None
    # INSEE city
    obj.insee_city = insee_city_from_api_data(data)
    obj.city = obj.insee_city.name if obj.insee_city else ""
    obj.department = obj.insee_city.department if obj.insee_city else ""


class Command(BaseCommand):
    help = "Synchronize 'agences' informations from the FT API."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["update-information", "fix-empty-safir"])
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def fix_empty_safir(self, data, *, wet_run=False):
        data_by_siret = {datum["siret"]: datum for datum in data if datum.get("siret")}
        for organization in PrescriberOrganization.objects.filter(
            Q(code_safir_pole_emploi="") | Q(code_safir_pole_emploi=None),
            kind=PrescriberOrganizationKind.PE,
            siret__in=data_by_siret,
        ):
            self.stdout.write(f"Organization={organization.pk} doesn't have a safir code")
            organization.code_safir_pole_emploi = data_by_siret[organization.siret]["codeSafir"]
            self.stdout.write(f"Set safir={organization.code_safir_pole_emploi} for organization={organization} ")
            if wet_run:
                try:
                    with transaction.atomic():
                        organization.save(update_fields={"code_safir_pole_emploi"})
                except IntegrityError:
                    self.stdout.write(f"ERR: safir={organization.code_safir_pole_emploi} already used")

    def update_information(self, data, *, wet_run=False):
        qs = PrescriberOrganization.objects.filter(kind=PrescriberOrganizationKind.PE).exclude(
            Q(code_safir_pole_emploi="") | Q(code_safir_pole_emploi=None)
        )
        mapping = [
            ("siret", "siret"),
            (name_from_api_data, "name"),
            (phone_from_api_data, "phone"),
            (email_from_api_data, "email"),
            (address_from_api_data, "address_line_1"),
            (address_extra_from_api_data, "address_line_2"),
            (post_code_from_api_data, "post_code"),
            (coordinates_from_api_data, "coords"),
            (insee_city_from_api_data, "insee_city"),
        ]
        for item in yield_sync_diff(
            [datum for datum in data if datum.get("siret")], "codeSafir", qs, "code_safir_pole_emploi", mapping
        ):
            if item.kind == DiffItemKind.DELETION:  # Ignore DELETION completely
                continue
            self.stdout.write(item.label)
            if item.kind == DiffItemKind.SUMMARY:  # Nothing more to do than display a message for SUMMARY
                continue

            safir = item.raw["codeSafir"]
            siret = item.raw["siret"]
            # Some agencies (with different location) share the same siret, this trigger the (siret, kind) unique
            # constraint, as we don't really care about siret for France Travail organization we circumvent that by
            # clearing the siret for the current one if it doesn't already exist or if is not the first one we see.
            if (
                siret
                and PrescriberOrganization.objects.filter(kind=PrescriberOrganizationKind.PE, siret=siret)
                .exclude(code_safir_pole_emploi=safir)
                .exists()
            ):
                siret = None
            if item.kind == DiffItemKind.ADDITION:
                obj = PrescriberOrganization(
                    kind=PrescriberOrganizationKind.PE,
                    code_safir_pole_emploi=safir,
                    is_authorized=True,
                    authorization_status=PrescriberAuthorizationStatus.VALIDATED,
                )
                fill_organization_from_api_data(obj, siret, item.raw)
                if wet_run:
                    obj.save()
            elif item.kind == DiffItemKind.EDITION:
                fill_organization_from_api_data(item.db_obj, siret, item.raw)
                if wet_run:
                    item.db_obj.save()

    @transaction.atomic
    def handle(self, *, action, wet_run=False, **options):
        data = pole_emploi_api_client().agences()
        match action:
            case "fix-empty-safir":
                self.fix_empty_safir(data, wet_run=wet_run)
            case "update-information":
                self.update_information(data, wet_run=wet_run)
