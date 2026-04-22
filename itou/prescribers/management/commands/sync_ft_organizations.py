from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.cities.models import City
from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE, lat_lon_to_coords
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.utils.apis.pole_emploi import pole_emploi_partenaire_api_client
from itou.utils.command import BaseCommand
from itou.utils.diff import CollectionDiffer, DiffItemKind, if_not_set_converter


def name_from_api_data(name):
    # Sometimes the `libelle` field can start with a "*",
    # it's most likely linked to the alias that agents can use instead of the official APE's email.
    return f"France Travail - {name.lstrip('*')}"


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    help = "Synchronize 'agences' informations from the FT API."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["update-information", "fix-empty-safir"])
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def fix_empty_safir(self, data):
        data_by_siret = {datum["siret"]: datum for datum in data if datum.get("siret")}
        for organization in PrescriberOrganization.objects.filter(
            Q(code_safir_pole_emploi="") | Q(code_safir_pole_emploi=None),
            kind=PrescriberOrganizationKind.FT,
            siret__in=data_by_siret,
        ):
            self.stdout.write(f"Organization={organization.pk} doesn't have a safir code")
            organization.code_safir_pole_emploi = data_by_siret[organization.siret]["codeSafir"]
            self.stdout.write(f"Set safir={organization.code_safir_pole_emploi} for organization={organization} ")
            try:
                with transaction.atomic():
                    organization.save(update_fields={"code_safir_pole_emploi"})
            except IntegrityError:
                self.stdout.write(f"ERR: safir={organization.code_safir_pole_emploi} already used")

    @staticmethod
    def set_extra_informations(obj, data):
        updated_fields = set()
        if "siret" in data:
            # Some agencies (with different location) share the same siret, this trigger the (siret, kind) unique
            # constraint, as we don't really care about siret for France Travail organization we circumvent that by
            # clearing the siret for the current one if it doesn't already exist or if is not the first one we see.
            siret = data["siret"].after
            siret_already_used = (
                PrescriberOrganization.objects.filter(kind=PrescriberOrganizationKind.FT, siret=siret)
                .exclude(code_safir_pole_emploi=obj.code_safir_pole_emploi)
                .exists()
            )
            obj.siret = None if siret_already_used else siret
            updated_fields.add("siret")
        if "coords" in data:
            obj.geocoding_score = BAN_API_RELIANCE_SCORE if data["coords"].after else None
            updated_fields.add("geocoding_score")
        if "insee_city" in data:
            city = data["insee_city"].after
            obj.city = city.name if city else ""
            obj.department = city.department if city else ""
            updated_fields.update(["city", "department"])

        return updated_fields

    def update_information(self, data):
        qs = PrescriberOrganization.objects.filter(kind=PrescriberOrganizationKind.FT).exclude(
            Q(code_safir_pole_emploi="") | Q(code_safir_pole_emploi=None)
        )
        differ = CollectionDiffer(
            qs,
            data,
            (["code_safir_pole_emploi"], ["codeSafir"]),
            watched_data={
                "siret": "siret",
                "name": "libelle",
                "phone": "contact.telephonePublic",
                "email": "contact.email",
                "address_line_1": "adressePrincipale.ligne4",
                "post_code": "adressePrincipale.bureauDistributeur",
                "coords": ("adressePrincipale.gpsLat", "adressePrincipale.gpsLon"),
                "insee_city": "adressePrincipale.communeImplantation",
            },
            comparative_data_converters={
                "siret": if_not_set_converter(None),
                "libelle": name_from_api_data,
                "contact.telephonePublic": if_not_set_converter(""),
                "contact.email": if_not_set_converter(""),
                ("adressePrincipale.gpsLat", "adressePrincipale.gpsLon"): lambda v: lat_lon_to_coords(*v),
                "adressePrincipale.communeImplantation": lambda v: City.objects.filter(code_insee=v).first(),
            },
        )
        for diff_item in differ:
            if diff_item.kind is DiffItemKind.REMOVED:  # Ignore DELETION completely
                continue
            self.stdout.write(diff_item.label())
            safir = diff_item.key[0]

            if diff_item.kind is DiffItemKind.ADDED:
                obj = PrescriberOrganization(
                    kind=PrescriberOrganizationKind.FT,
                    code_safir_pole_emploi=safir,
                    authorization_status=PrescriberAuthorizationStatus.VALIDATED,
                )
                for current_item_attr, comparative_item_value in diff_item.data.items():
                    setattr(obj, current_item_attr, comparative_item_value.after)
                self.set_extra_informations(obj, diff_item.data)
                obj.save()
            elif diff_item.kind is DiffItemKind.UPDATED:
                for current_item_attr, data_diff in diff_item.data.items():
                    setattr(diff_item.current_item, current_item_attr, data_diff.after)
                updated_fields = self.set_extra_informations(diff_item.current_item, diff_item.data)
                diff_item.current_item.updated_at = timezone.now()
                diff_item.current_item.save(update_fields={*diff_item.data.keys(), *updated_fields, "updated_at"})

        self.stdout.write(differ.summary_label())

    @dry_runnable
    def handle(self, *, action, wet_run=False, **options):
        data = pole_emploi_partenaire_api_client().agences()
        match action:
            case "fix-empty-safir":
                self.fix_empty_safir(data)
            case "update-information":
                self.update_information(data)
