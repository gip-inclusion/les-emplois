import datetime
import enum
import functools

from django.conf import settings
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.cities.models import City
from itou.common_apps.address.models import lat_lon_to_coords
from itou.insertion.models import (
    SOURCE_DORA_VALUE,
    GenericReferenceItem,
    GenericReferenceItemKind,
    GenericReferenceItemSource,
    Service,
    Structure,
)
from itou.utils import constants as global_constants, diff
from itou.utils.apis.data_inclusion import DataInclusionApiClient, DataInclusionApiItemsIterator
from itou.utils.apis.dora import DoraAPIClient, DoraApiItemsIterator
from itou.utils.command import BaseCommand


class ArgumentData(enum.StrEnum):
    REFERENCES = "references"
    STRUCTURES = "structures"
    SERVICES = "services"


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
        return City.objects.only("pk").in_bulk(field_name="code_insee")

    @functools.lru_cache(maxsize=len(GenericReferenceItemSource) * len(GenericReferenceItemKind))
    def reference_data_by_value(self, source, kind):
        return (
            GenericReferenceItem.objects.filter(source=source, kind=kind).distinct("value").in_bulk(field_name="value")
        )

    def get_reference_set_from_data(self, data, key, source, kind):
        return [self.reference_data_by_value(source, kind)[value] for value in (data[key] or [])]

    def import_data_inclusion_reference_data(self, client):
        self.logger.info("Importing data·inclusion references data")
        to_create = []

        reference_data = [
            (GenericReferenceItemKind.FEE, "frais"),
            (GenericReferenceItemKind.MOBILIZATION, "modes-mobilisation"),
            (GenericReferenceItemKind.MOBILIZATION_PUBLIC, "personnes-mobilisatrices"),
            (GenericReferenceItemKind.NETWORK, "reseaux-porteurs"),
            (GenericReferenceItemKind.PUBLIC, "publics"),
            (GenericReferenceItemKind.RECEPTION, "modes-accueil"),
            (GenericReferenceItemKind.SERVICE_KIND, "types-services"),
            (GenericReferenceItemKind.THEMATIC, "thematiques"),
        ]
        for kind, api_kind in reference_data:
            differ = diff.CollectionDiffer(
                GenericReferenceItem.objects.filter(source=GenericReferenceItemSource.DATA_INCLUSION, kind=kind),
                client.doc(api_kind),
                "value",
                {"label": "label", "description": "description"},
            )
            for diff_item in differ:
                self.logger.info(diff_item.label())

                if diff_item.kind is diff.DiffItemKind.ADDED:
                    to_create.append(
                        GenericReferenceItem(
                            source=GenericReferenceItemSource.DATA_INCLUSION,
                            kind=kind,
                            value=diff_item.key[0],
                            label=diff_item.data["label"].after,
                            description=diff_item.data["description"].after,
                        )
                    )
                elif diff_item.kind is diff.DiffItemKind.UPDATED:
                    for current_item_attr, data_diff in diff_item.data.items():
                        setattr(diff_item.current_item, current_item_attr, data_diff.after)
                    diff_item.current_item.save(update_fields={*diff_item.data.keys(), "updated_at"})
                elif diff_item.kind is diff.DiffItemKind.REMOVED:
                    diff_item.current_item.delete()

            self.logger.info(differ.summary_label())

        GenericReferenceItem.objects.bulk_create(to_create)

    def import_dora_reference_data(self, client):
        self.logger.info("Importing DORA references data")
        to_create = []
        dora_kind_mapping = {
            "beneficiary_access_mode": GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
            "coach_orientation_mode": GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            "funding_label": GenericReferenceItemKind.FUNDING_LABEL,
        }

        differ = diff.CollectionDiffer(
            GenericReferenceItem.objects.filter(source=GenericReferenceItemSource.DORA),
            client.reference_data(),
            ["kind", "value"],
            watched_data={"label": "label"},
            comparative_data_converters={"kind": dora_kind_mapping.get},
        )
        for diff_item in differ:
            self.logger.info(diff_item.label())

            if diff_item.kind is diff.DiffItemKind.ADDED:
                to_create.append(
                    GenericReferenceItem(
                        source=GenericReferenceItemSource.DORA,
                        kind=dora_kind_mapping[diff_item.comparative_item["kind"]],
                        value=diff_item.comparative_item["value"],
                        label=diff_item.comparative_item["label"],
                    )
                )
            elif diff_item.kind is diff.DiffItemKind.UPDATED:
                for current_item_attr, data_diff in diff_item.data.items():
                    setattr(diff_item.current_item, current_item_attr, data_diff.after)
                diff_item.current_item.save(update_fields={*diff_item.data.keys(), "updated_at"})
            elif diff_item.kind is diff.DiffItemKind.REMOVED:
                diff_item.current_item.delete()

        self.logger.info(differ.summary_label())

        GenericReferenceItem.objects.bulk_create(to_create)

    def import_sources(self, client):
        self.logger.info("Import sources")
        to_create = []

        differ = diff.CollectionDiffer(
            GenericReferenceItem.objects.filter(
                source=GenericReferenceItemSource.DATA_INCLUSION, kind=GenericReferenceItemKind.SOURCE
            ),
            client.sources(),
            (["value"], ["slug"]),
            watched_data={"label": "nom", "description": "description"},
        )
        for diff_item in differ:
            self.logger.info(diff_item.label())

            if diff_item.kind is diff.DiffItemKind.ADDED:
                to_create.append(
                    GenericReferenceItem(
                        source=GenericReferenceItemSource.DATA_INCLUSION,
                        kind=GenericReferenceItemKind.SOURCE,
                        value=diff_item.comparative_item["slug"],
                        label=diff_item.comparative_item["nom"],
                        description=diff_item.comparative_item["description"],
                    )
                )
            elif diff_item.kind is diff.DiffItemKind.UPDATED:
                for current_item_attr, data_diff in diff_item.data.items():
                    setattr(diff_item.current_item, current_item_attr, data_diff.after)
                diff_item.current_item.save(update_fields={*diff_item.data.keys(), "updated_at"})
            elif diff_item.kind is diff.DiffItemKind.REMOVED:
                diff_item.current_item.delete()

        self.logger.info(differ.summary_label())

        GenericReferenceItem.objects.bulk_create(to_create)

    def _void_if_max_len(self, obj, field_name, replace_with=""):
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
            setattr(obj, field_name, replace_with)

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

        structure.source = self.reference_data_by_value(
            GenericReferenceItemSource.DATA_INCLUSION, GenericReferenceItemKind.SOURCE
        )[data["source"]]
        structure.source_link = data["lien_source"] or ""
        self._void_if_max_len(structure, "source_link")

        structure.siret = data["siret"] or ""

        structure.name = data["nom"]
        structure.description = data["description"] or ""

        structure.website = data["site_web"] or ""
        self._void_if_max_len(structure, "website")

        structure.email = data["courriel"] or ""
        structure.phone = data["telephone"] or ""
        self._void_if_max_len(structure, "phone")

        structure.opening_hours = data["horaires_accueil"] or ""

        self._fill_geolocation_from_api_data(structure, data)

        structure.updated_on = data["date_maj"]

    def import_structures(self, client, sources):
        self.logger.info("Importing structures")

        differ = diff.CollectionDiffer(
            Structure.objects.all(),
            DataInclusionApiItemsIterator(client.structures, page_size=10_000, params={"sources": sources}),
            (["uid"], ["id"]),
            watched_data={"updated_on": "date_maj"},
            comparative_data_converters={"date_maj": datetime.date.fromisoformat},
        )
        for diff_item in differ:
            self.logger.info(diff_item.label())

            if diff_item.kind is diff.DiffItemKind.ADDED:
                structure = Structure()
                self._fill_structure_from_api_data(structure, diff_item.comparative_item)
                structure.save()
            elif diff_item.kind is diff.DiffItemKind.UPDATED:
                self._fill_structure_from_api_data(diff_item.current_item, diff_item.comparative_item)
                diff_item.current_item.save()
            elif diff_item.kind is diff.DiffItemKind.REMOVED:
                diff_item.current_item.delete()

        self.logger.info(differ.summary_label())

    def _fill_service_from_dora_api_data(self, service, dora_services, non_orientable_structures):
        dora_data = dora_services.get(service.uid)

        service.is_orientable_with_form = (
            service.structure.uid not in non_orientable_structures
            and dora_data
            and dora_data["is_orientable_with_form"]
        )

        if service.source.value != SOURCE_DORA_VALUE or not dora_data:
            if service.source.value == SOURCE_DORA_VALUE:
                self.logger.warning("Service uid=%s was not returned by the DORA API", service.uid)
            service.dora_synced_at = None
            return

        service.description_short = dora_data["short_desc"]

        service.access_conditions_dora = dora_data["access_conditions"]

        service.mobilization_modes_beneficiaries_external_form_link = dora_data[
            "beneficiaries_access_modes_external_form_link"
        ]
        service.mobilization_modes_beneficiaries_external_form_link_text = dora_data[
            "beneficiaries_access_modes_external_form_link_text"
        ]
        service.mobilization_modes_beneficiaries_other = dora_data["beneficiaries_access_modes_other"]
        service.mobilization_modes_professionals_external_form_link = dora_data[
            "coach_orientation_modes_external_form_link"
        ]
        service.mobilization_modes_professionals_external_form_link_text = dora_data[
            "coach_orientation_modes_external_form_link_text"
        ]
        service.mobilization_modes_professionals_other = dora_data["coach_orientation_modes_other"]

        service.credentials = dora_data["credentials"]
        service.credentials_documents = dora_data["forms"]
        service.credentials_online_form = dora_data["online_form"]

        # TODO: Try to parse it as a OSM opening hours to fill `.opening_hours`
        service.opening_hours_text = dora_data["recurrence"]

        service.contact_is_public = dora_data["is_contact_info_public"]
        service.contact_full_name = dora_data["contact_name"]
        service.contact_phone = dora_data["contact_phone"]
        service.contact_email = dora_data["contact_email"]

        service.average_orientation_response_delay_days = dora_data["average_orientation_response_delay_days"]
        service.dora_synced_at = timezone.now()

    def _fill_service_related_fields_from_data(self, service, data, dora_services, is_creation):
        def do_m2m_operation(attr, objs):
            """Heavily reduce queries numbers when creating new object.

            I would have used .set() but most ManyRelatedManager operations clear
            the prefetch cache so we can't rely on it and have to make that kind of things"""
            m2m_manager = getattr(service, attr)
            if is_creation:
                m2m_manager.add(*objs)
            else:
                m2m_manager.set(objs)

        do_m2m_operation(
            "thematics",
            self.get_reference_set_from_data(
                data, "thematiques", GenericReferenceItemSource.DATA_INCLUSION, GenericReferenceItemKind.THEMATIC
            ),
        )
        do_m2m_operation(
            "publics",
            self.get_reference_set_from_data(
                data, "publics", GenericReferenceItemSource.DATA_INCLUSION, GenericReferenceItemKind.PUBLIC
            ),
        )
        do_m2m_operation(
            "receptions",
            self.get_reference_set_from_data(
                data, "modes_accueil", GenericReferenceItemSource.DATA_INCLUSION, GenericReferenceItemKind.RECEPTION
            ),
        )
        do_m2m_operation(
            "mobilizations",
            self.get_reference_set_from_data(
                data,
                "modes_mobilisation",
                GenericReferenceItemSource.DATA_INCLUSION,
                GenericReferenceItemKind.MOBILIZATION,
            ),
        )
        do_m2m_operation(
            "mobilization_publics",
            self.get_reference_set_from_data(
                data,
                "mobilisable_par",
                GenericReferenceItemSource.DATA_INCLUSION,
                GenericReferenceItemKind.MOBILIZATION_PUBLIC,
            ),
        )
        dora_data = dora_services.get(service.uid)
        if service.source.value != SOURCE_DORA_VALUE or not dora_data:
            return

        do_m2m_operation(
            "funding_labels",
            self.get_reference_set_from_data(
                dora_data,
                "funding_labels",
                GenericReferenceItemSource.DORA,
                GenericReferenceItemKind.FUNDING_LABEL,
            ),
        )
        do_m2m_operation(
            "mobilization_modes_beneficiaries",
            self.get_reference_set_from_data(
                dora_data,
                "beneficiaries_access_modes",
                GenericReferenceItemSource.DORA,
                GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
            ),
        )
        do_m2m_operation(
            "mobilization_modes_professionals",
            self.get_reference_set_from_data(
                dora_data,
                "coach_orientation_modes",
                GenericReferenceItemSource.DORA,
                GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            ),
        )

    def _fill_and_save_service_from_api_data(self, obj, data, dora_services, non_orientable_structures, structures):
        service, is_creation = (obj, False) if obj is not None else (Service(), True)
        # Fill non ManyToManyField
        service.uid = data["id"]

        service.source = self.reference_data_by_value(
            GenericReferenceItemSource.DATA_INCLUSION, GenericReferenceItemKind.SOURCE
        )[data["source"]]
        service.source_link = data["lien_source"] or ""
        self._void_if_max_len(service, "source_link")

        service.structure = structures.get(data["structure_id"])
        if not service.structure_id:  # Shouldn't happen, but we don't want to block everything
            self.logger.warning(
                "Service uid=%s declare a structure_id=%s but it was not found",
                service.uid,
                data["structure_id"],
            )
            return

        service.name = data["nom"]

        service.description = data["description"] or ""

        service.kind = self.reference_data_by_value(
            GenericReferenceItemSource.DATA_INCLUSION, GenericReferenceItemKind.SERVICE_KIND
        ).get(data["type"])

        service.fee = self.reference_data_by_value(
            GenericReferenceItemSource.DATA_INCLUSION, GenericReferenceItemKind.FEE
        ).get(data["frais"])
        service.fee_details = data["frais_precisions"] or ""

        service.publics_details = data["publics_precisions"] or ""  # service.public is a ManyToManyField

        service.access_conditions_di = data["conditions_acces"] or ""

        service.eligibility_zones = data["zone_eligibilite"] or []

        service.mobilization_modes_professionals_external_form_link = data["lien_mobilisation"] or ""

        service.mobilizations_details = (
            data["mobilisation_precisions"] or ""
        )  # service.mobilizations is a ManyToManyField

        service.opening_hours = data["horaires_accueil"] or ""

        service.contact_full_name = data["contact_nom_prenom"] or ""
        service.contact_email = data["courriel"] or ""
        self._void_if_max_len(service, "contact_email")
        service.contact_phone = data["telephone"] or ""
        self._void_if_max_len(service, "contact_phone")

        self._fill_geolocation_from_api_data(service, data)
        self._fill_service_from_dora_api_data(service, dora_services, non_orientable_structures)

        service.updated_on = data["date_maj"]

        service.save()  # Save to have a PK for ManyToManyField fields

        self._fill_service_related_fields_from_data(service, data, dora_services, is_creation)  # Fill ManyToManyField

    def import_services(self, di_client, dora_client, sources, non_orientable_structures):
        self.logger.info("Importing services")
        dora_services = {"dora--" + item["id"]: item for item in DoraApiItemsIterator(dora_client.emplois_services)}
        structures = Structure.objects.only("uid").in_bulk(field_name="uid")

        differ = diff.CollectionDiffer(
            Service.objects.all(),
            DataInclusionApiItemsIterator(di_client.services, page_size=10_000, params={"sources": sources}),
            (["uid"], ["id"]),
            watched_data={"updated_on": "date_maj"},
            comparative_data_converters={"date_maj": datetime.date.fromisoformat},
        )
        for diff_item in differ:
            self.logger.info(diff_item.label())

            if diff_item.kind is diff.DiffItemKind.ADDED:
                self._fill_and_save_service_from_api_data(
                    None,
                    diff_item.comparative_item,
                    dora_services,
                    non_orientable_structures,
                    structures,
                )
            elif diff_item.kind is diff.DiffItemKind.UPDATED:
                self._fill_and_save_service_from_api_data(
                    diff_item.current_item,
                    diff_item.comparative_item,
                    dora_services,
                    non_orientable_structures,
                    structures,
                )
            elif diff_item.kind is diff.DiffItemKind.REMOVED:
                diff_item.current_item.delete()

        self.logger.info(differ.summary_label())

    def import_disabled_structures(self, non_orientable_structures):
        self.logger.info("Import disabled structures from DORA")

        updated_services = Service.objects.filter(
            structure__uid__in=non_orientable_structures,
            is_orientable_with_form=True,
        ).update(is_orientable_with_form=False)
        self.logger.info(
            "Change 'is_orientable_with_form' ('True' -> 'False') for count=%d services based on count=%d structures",
            updated_services,
            len(non_orientable_structures),
        )

    @dry_runnable
    def handle(self, *args, data, **options):
        with (
            DataInclusionApiClient(
                global_constants.API_DATA_INCLUSION_BASE_URL,
                settings.API_DATA_INCLUSION_TOKEN,
            ) as di_client,
            DoraAPIClient(settings.DORA_API_BASE_URL, settings.DORA_API_TOKEN) as dora_client,
        ):
            if ArgumentData.REFERENCES in data:
                self.import_data_inclusion_reference_data(di_client)
                self.import_dora_reference_data(dora_client)
                self.import_sources(di_client)

            if ArgumentData.STRUCTURES in data or ArgumentData.SERVICES in data:
                # `emplois-de-linclusion` is omitted, we already have the structures locally and no services yet.
                sources_except_emplois = sorted(
                    source["slug"] for source in di_client.sources() if source["slug"] != "emplois-de-linclusion"
                )
                # Some data·inclusion services are non orientable with DORA's form.
                non_orientable_structures = dora_client.disabled_dora_form_di_structures()

            if ArgumentData.STRUCTURES in data:
                self.import_structures(di_client, sources_except_emplois)
                self.import_disabled_structures(non_orientable_structures)

            if ArgumentData.SERVICES in data:
                self.import_services(di_client, dora_client, sources_except_emplois, non_orientable_structures)
