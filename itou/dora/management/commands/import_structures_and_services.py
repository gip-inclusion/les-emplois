import datetime
import enum
import functools

from django.conf import settings
from itoutils.django.commands import dry_runnable

from itou.cities.models import City
from itou.common_apps.address.models import lat_lon_to_coords
from itou.dora.models import SOURCE_DORA_VALUE, ReferenceDatum, ReferenceDatumKind, Service, Structure
from itou.utils import constants as global_constants
from itou.utils.apis.data_inclusion import DataInclusionApiV1Client, DataInclusionApiV1ItemsIterator
from itou.utils.apis.dora import DoraAPIClient
from itou.utils.command import BaseCommand
from itou.utils.sync import DiffItemKind, yield_sync_diff


class ArgumentData(enum.StrEnum):
    REFERENCES = "references"
    STRUCTURES = "structures"
    SERVICES = "services"
    DORA = "dora"


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    help = "Import data·inclusion/DORA structures and services"

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "--data", choices=list(ArgumentData), default=list(ArgumentData), type=ArgumentData, nargs="+"
        )
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @functools.cached_property
    def cities_by_code_insee(self):
        return City.objects.in_bulk(field_name="code_insee")

    @functools.lru_cache(maxsize=len(ReferenceDatumKind))
    def reference_data_by_value(self, kind):
        return ReferenceDatum.objects.filter(kind=kind).distinct("value").in_bulk(field_name="value")

    @functools.cached_property
    def disabled_dora_form_di_structures(self):
        return DoraAPIClient(settings.DORA_API_BASE_URL, settings.DORA_API_TOKEN).disabled_dora_form_di_structures()

    @functools.cached_property
    def dora_services(self):
        return {
            "dora--" + r["id"]: {**r, "uid": "dora--" + r["id"]}
            for r in DoraAPIClient(settings.DORA_API_BASE_URL, settings.DORA_API_TOKEN).emplois_services()
        }

    def import_reference_data(self, client):
        self.logger.info("Importing references data")
        to_create, to_update = [], []

        reference_data = [
            (ReferenceDatumKind.FEE, "frais"),
            (ReferenceDatumKind.RECEPTION, "modes-accueil"),
            (ReferenceDatumKind.MOBILIZATION, "modes-mobilisation"),
            (ReferenceDatumKind.MOBILIZATION_PUBLIC, "personnes-mobilisatrices"),
            (ReferenceDatumKind.PUBLIC, "publics"),
            (ReferenceDatumKind.NETWORK, "reseaux-porteurs"),
            (ReferenceDatumKind.THEMATIC, "thematiques"),
            (ReferenceDatumKind.SERVICE_KIND, "types-services"),
        ]
        for kind, api_kind in reference_data:
            diff_items = yield_sync_diff(
                client.doc(api_kind),
                "value",
                ReferenceDatum.objects.filter(kind=kind),
                "value",
                [("label", "label"), ("description", "description")],
            )
            for item in diff_items:
                self.logger.info(item.label)

                if item.kind == DiffItemKind.ADDITION:
                    to_create.append(
                        ReferenceDatum(
                            kind=kind,
                            value=item.raw["value"],
                            label=item.raw["label"],
                            description=item.raw["description"],
                        )
                    )
                elif item.kind == DiffItemKind.EDITION:
                    item.db_obj.label = item.raw["label"]
                    item.db_obj.description = item.raw["description"]
                    to_update.append(item.db_obj)
                elif item.kind == DiffItemKind.DELETION:
                    item.db_obj.delete()

        ReferenceDatum.objects.bulk_create(to_create)
        ReferenceDatum.objects.bulk_update(to_update, fields={"label", "description"})

    def import_sources(self, client):
        self.logger.info("Import sources")
        to_create, to_update = [], []

        diff_items = yield_sync_diff(
            client.sources(),
            "slug",
            ReferenceDatum.objects.filter(kind=ReferenceDatumKind.SOURCE),
            "value",
            [("nom", "label"), ("description", "description")],
        )
        for item in diff_items:
            self.logger.info(item.label)

            if item.kind == DiffItemKind.ADDITION:
                to_create.append(
                    ReferenceDatum(
                        kind=ReferenceDatumKind.SOURCE,
                        value=item.raw["slug"],
                        label=item.raw["nom"],
                        description=item.raw["description"],
                    )
                )
            elif item.kind == DiffItemKind.EDITION:
                item.db_obj.label = item.raw["nom"]
                item.db_obj.description = item.raw["description"]
                to_update.append(item.db_obj)
            elif item.kind == DiffItemKind.DELETION:
                item.db_obj.delete()

        ReferenceDatum.objects.bulk_create(to_create)
        ReferenceDatum.objects.bulk_update(to_update, fields={"label", "description"})

    def _truncate_field_if_greater_than_max_length(self, obj, field_name):
        field_value_length = len(getattr(obj, field_name))
        max_length = obj._meta.get_field(field_name).max_length
        if field_value_length > max_length:
            self.logger.warning(
                "Truncate %r for uid=%s because value length %d is greater than maximum length %d",
                field_name,
                obj.uid,
                field_value_length,
                max_length,
            )
            setattr(obj, field_name, "")

    def _fill_geolocation_from_api_data(self, obj, data):
        obj.address_line_1 = data["adresse"] or ""
        obj.address_line_2 = data["complement_adresse"] or ""
        obj.post_code = data["code_postal"] or ""
        obj.city = data["commune"] or ""

        obj.insee_city = self.cities_by_code_insee.get(data["code_insee"])
        if data["code_insee"] and not obj.insee_city:
            self.logger.warning(
                "%s with uid=%s without City(code_insee=%s)", obj.__class__.__name__, obj.uid, data["code_insee"]
            )

        obj.coordinates = lat_lon_to_coords(data["latitude"], data["longitude"])

    def _fill_structure_from_api_data(self, structure, data):
        structure.uid = data["id"]

        structure.source = self.reference_data_by_value(ReferenceDatumKind.SOURCE)[data["source"]]
        structure.source_link = data["lien_source"] or ""
        self._truncate_field_if_greater_than_max_length(structure, "source_link")

        structure.siret = data["siret"] or ""

        structure.name = data["nom"]
        structure.description = data["description"] or ""

        structure.email = data["courriel"] or ""
        structure.phone = data["telephone"] or ""
        self._truncate_field_if_greater_than_max_length(structure, "phone")

        self._fill_geolocation_from_api_data(structure, data)

        structure.updated_on = data["date_maj"]

    def import_structures(self, client):
        self.logger.info("Importing structures")

        diff_items = yield_sync_diff(
            DataInclusionApiV1ItemsIterator(client.structures),
            "id",
            Structure.objects.all(),
            "uid",
            [(lambda obj: datetime.date.fromisoformat(obj["date_maj"]), "updated_on")],
        )
        for item in diff_items:
            self.logger.info(item.label)

            if item.kind == DiffItemKind.ADDITION:
                structure = Structure()
                self._fill_structure_from_api_data(structure, item.raw)
                structure.save()
            elif item.kind == DiffItemKind.EDITION:
                self._fill_structure_from_api_data(item.db_obj, item.raw)
                item.db_obj.save()
            elif item.kind == DiffItemKind.DELETION:
                item.db_obj.delete()

    def _fill_service_from_dora_api_data(self, service):
        if service.source.value == SOURCE_DORA_VALUE:
            dora_data = self.dora_services.get(service.uid)
            if not dora_data:
                self.logger.warning("Service uid=%s was not returned by the DORA API", service.uid)
                return
            service.description_short = dora_data["short_desc"]
            service.is_orientable_with_form = dora_data["is_orientable_with_form"]
            service.average_orientation_response_delay_days = dora_data["average_orientation_response_delay_days"]
        else:
            service.description_short = ""
            service.is_orientable_with_form = service.structure.uid not in self.disabled_dora_form_di_structures
            service.average_orientation_response_delay_days = None

    def _fill_and_save_service_from_api_data(self, service, data):
        # Fill non ManyToManyField
        service.uid = data["id"]

        service.source = self.reference_data_by_value(ReferenceDatumKind.SOURCE)[data["source"]]
        service.source_link = data["lien_source"] or ""
        self._truncate_field_if_greater_than_max_length(service, "source_link")

        try:
            service.structure = Structure.objects.get(uid=data["structure_id"])
        except Structure.DoesNotExist:  # Shouldn't happen but if it does we don't want to block everything
            self.logger.warning(
                "Service uid=%s declare a structure_id=%s but it was not found",
                service.uid,
                data["structure_id"],
            )
            return

        service.name = data["nom"]

        service.description = data["description"] or ""

        service.kind = self.reference_data_by_value(ReferenceDatumKind.SERVICE_KIND).get(data["type"])

        service.fee = self.reference_data_by_value(ReferenceDatumKind.FEE).get(data["frais"])
        service.fee_details = data["frais_precisions"] or ""

        service.publics_details = data["publics_precisions"] or ""  # service.public is a ManyToManyField

        service.access_conditions = data["conditions_acces"] or ""

        service.mobilizations_details = (
            data["mobilisation_precisions"] or ""
        )  # service.mobilizations is a ManyToManyField
        service.mobilization_link = data["lien_mobilisation"] or ""
        self._truncate_field_if_greater_than_max_length(service, "mobilization_link")

        service.opening_hours = data["horaires_accueil"] or ""

        service.contact_full_name = data["contact_nom_prenom"] or ""
        service.contact_email = data["courriel"] or ""
        self._truncate_field_if_greater_than_max_length(service, "contact_email")
        service.contact_phone = data["telephone"] or ""
        self._truncate_field_if_greater_than_max_length(service, "contact_phone")

        self._fill_geolocation_from_api_data(service, data)
        self._fill_service_from_dora_api_data(service)

        service.updated_on = data["date_maj"]

        service.save()  # Save to have a PK for ManyToManyField fields

        # Fill ManyToManyField
        service.thematics.set(
            [self.reference_data_by_value(ReferenceDatumKind.THEMATIC)[value] for value in (data["thematiques"] or [])]
        )
        service.publics.set(
            [self.reference_data_by_value(ReferenceDatumKind.PUBLIC)[value] for value in (data["publics"] or [])]
        )
        service.receptions.set(
            [
                self.reference_data_by_value(ReferenceDatumKind.RECEPTION)[value]
                for value in (data["modes_accueil"] or [])
            ]
        )
        service.mobilizations.set(
            [
                self.reference_data_by_value(ReferenceDatumKind.MOBILIZATION)[value]
                for value in (data["modes_mobilisation"] or [])
            ]
        )
        service.mobilization_publics.set(
            [
                self.reference_data_by_value(ReferenceDatumKind.MOBILIZATION_PUBLIC)[value]
                for value in (data["mobilisable_par"] or [])
            ]
        )

    def import_services(self, client):
        self.logger.info("Importing services")

        diff_items = yield_sync_diff(
            DataInclusionApiV1ItemsIterator(client.services),
            "id",
            Service.objects.all(),
            "uid",
            [(lambda obj: datetime.date.fromisoformat(obj["date_maj"]), "updated_on")],
        )
        for item in diff_items:
            self.logger.info(item.label)

            if item.kind == DiffItemKind.ADDITION:
                self._fill_and_save_service_from_api_data(Service(), item.raw)
            elif item.kind == DiffItemKind.EDITION:
                self._fill_and_save_service_from_api_data(item.db_obj, item.raw)
            elif item.kind == DiffItemKind.DELETION:
                item.db_obj.delete()

    def import_dora(self):
        self.logger.info("Import additional informations from DORA")

        # Some data·inclusion services are non orientable with DORA's form
        updated_services = Service.objects.filter(
            structure__uid__in=self.disabled_dora_form_di_structures,
            is_orientable_with_form=True,
        ).update(is_orientable_with_form=False)
        self.logger.info(
            "Change 'is_orientable_with_form' ('True' -> 'False') for count=%d services based on count=%d structures",
            updated_services,
            len(self.disabled_dora_form_di_structures),
        )

        # Synchronize DORA's extraneous information
        diff_items = yield_sync_diff(
            self.dora_services.values(),
            "uid",
            Service.objects.filter(source__value=SOURCE_DORA_VALUE),
            "uid",
            [
                ("short_desc", "description_short"),
                ("is_orientable_with_form", "is_orientable_with_form"),
                ("average_orientation_response_delay_days", "average_orientation_response_delay_days"),
            ],
        )
        for item in diff_items:
            if item.kind in {DiffItemKind.ADDITION, DiffItemKind.DELETION}:
                continue  # Ignore altogether as DORA it not our main source so treat them as false positive
            self.logger.info(item.label)

            if item.kind == DiffItemKind.EDITION:
                self._fill_service_from_dora_api_data(item.db_obj)
                item.db_obj.save(
                    update_fields={
                        "description_short",
                        "is_orientable_with_form",
                        "average_orientation_response_delay_days",
                    }
                )

    @dry_runnable
    def handle(self, *args, data, **options):
        with DataInclusionApiV1Client(
            global_constants.API_DATA_INCLUSION_BASE_URL,
            settings.API_DATA_INCLUSION_TOKEN,
        ) as client:
            if ArgumentData.REFERENCES in data:
                self.import_reference_data(client)
                self.import_sources(client)

            if ArgumentData.STRUCTURES in data:
                self.import_structures(client)

            if ArgumentData.SERVICES in data:
                self.import_services(client)

            if ArgumentData.DORA in data:
                self.import_dora()
