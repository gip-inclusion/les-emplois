import datetime
import enum
import functools

from django.conf import settings
from itoutils.django.commands import dry_runnable

from itou.cities.models import City
from itou.common_apps.address.models import lat_lon_to_coords
from itou.insertion.models import (
    GenericReferenceItem,
    GenericReferenceItemKind,
    GenericReferenceItemSource,
    Service,
    Structure,
)
from itou.utils import constants as global_constants, diff
from itou.utils.apis.data_inclusion import DataInclusionApiClient, DataInclusionApiItemsIterator
from itou.utils.command import BaseCommand
from itou.utils.db import lock_timeout


class ArgumentData(enum.StrEnum):
    REFERENCES = "references"
    STRUCTURES = "structures"
    SERVICES = "services"


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    help = "Import data·inclusion structures and services"

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "--data", choices=list(ArgumentData), default=list(ArgumentData), type=ArgumentData, nargs="+"
        )
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--force", dest="force_update", action="store_true")

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

        structure.accessibilite_lieu = data["accessibilite_lieu"] or ""
        self._void_if_max_len(structure, "accessibilite_lieu")

        self._fill_geolocation_from_api_data(structure, data)

        structure.updated_on = data["date_maj"]

    def import_structures(self, client, sources, *, force_update=False):
        self.logger.info("Importing structures")

        differ = diff.CollectionDiffer(
            Structure.include_inactive.all(),
            DataInclusionApiItemsIterator(client.structures, page_size=1000, params={"sources": sources}),
            (["uid"], ["id"]),
            watched_data={"updated_on": "date_maj"},
            comparative_data_converters={"date_maj": datetime.date.fromisoformat},
            force_update=force_update,
        )
        removed_uids = []
        for diff_item in differ:
            self.logger.info(diff_item.label())

            if diff_item.kind is diff.DiffItemKind.REMOVED:
                removed_uids.append(diff_item.key[0])
                continue

            if diff_item.kind is diff.DiffItemKind.UPDATED:
                structure = diff_item.current_item
            else:
                structure = Structure()
            self._fill_structure_from_api_data(structure, diff_item.comparative_item)
            structure.save()
            networks = self.get_reference_set_from_data(
                diff_item.comparative_item,
                "reseaux_porteurs",
                GenericReferenceItemSource.DATA_INCLUSION,
                GenericReferenceItemKind.NETWORK,
            )
            if diff_item.kind is diff.DiffItemKind.ADDED:
                structure.reseaux_porteurs.add(*networks)
            else:
                structure.reseaux_porteurs.set(networks)

        Structure.include_inactive.filter(is_active=True, uid__in=removed_uids).update(is_active=False)
        Structure.include_inactive.filter(is_active=False).exclude(uid__in=removed_uids).update(is_active=True)

        self.logger.info(differ.summary_label())

    def _fill_and_save_service_from_api_data(self, obj, data, structures):
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

        service.lien_mobilisation = data["lien_mobilisation"] or ""
        self._void_if_max_len(service, "lien_mobilisation")

        service.mobilizations_details = (
            data["mobilisation_precisions"] or ""
        )  # service.mobilizations is a ManyToManyField

        service.opening_hours = data["horaires_accueil"] or ""

        service.volume_horaire_hebdomadaire = data.get("volume_horaire_hebdomadaire") or None
        service.nombre_semaines = data.get("nombre_semaines") or None

        service.contact_full_name = data["contact_nom_prenom"] or ""
        service.contact_email = data["courriel"] or ""
        self._void_if_max_len(service, "contact_email")
        service.contact_phone = data["telephone"] or ""
        self._void_if_max_len(service, "contact_phone")

        self._fill_geolocation_from_api_data(service, data)

        # Producer-specific blob; see Service.extra for the expected DORA shape.
        service.extra = data.get("extra")

        service.updated_on = data["date_maj"]

        service.save()  # Save to have a PK for ManyToManyField fields

        # .add() on creation avoids the extra SELECT that .set() does to diff existing rows.
        related_fields = [
            ("thematics", "thematiques", GenericReferenceItemKind.THEMATIC),
            ("publics", "publics", GenericReferenceItemKind.PUBLIC),
            ("receptions", "modes_accueil", GenericReferenceItemKind.RECEPTION),
            ("mobilizations", "modes_mobilisation", GenericReferenceItemKind.MOBILIZATION),
            ("mobilization_publics", "mobilisable_par", GenericReferenceItemKind.MOBILIZATION_PUBLIC),
        ]
        for attr, key, kind in related_fields:
            objs = self.get_reference_set_from_data(data, key, GenericReferenceItemSource.DATA_INCLUSION, kind)
            relation = getattr(service, attr)
            if is_creation:
                relation.add(*objs)
            else:
                relation.set(objs)

    def import_services(self, di_client, sources, *, force_update=False):
        self.logger.info("Importing services")
        structures = Structure.include_inactive.only("uid").in_bulk(field_name="uid")

        differ = diff.CollectionDiffer(
            Service.include_inactive.all(),
            DataInclusionApiItemsIterator(
                di_client.services, page_size=1000, params={"sources": sources, "extra": True}
            ),
            (["uid"], ["id"]),
            watched_data={"updated_on": "date_maj"},
            comparative_data_converters={"date_maj": datetime.date.fromisoformat},
            force_update=force_update,
        )
        removed_uids = []
        for diff_item in differ:
            self.logger.info(diff_item.label())

            if diff_item.kind is diff.DiffItemKind.REMOVED:
                removed_uids.append(diff_item.key[0])
                continue

            self._fill_and_save_service_from_api_data(
                diff_item.current_item if diff_item.kind is diff.DiffItemKind.UPDATED else None,
                diff_item.comparative_item,
                structures,
            )

        Service.include_inactive.filter(is_active=True, uid__in=removed_uids).update(is_active=False)
        Service.include_inactive.filter(is_active=False).exclude(uid__in=removed_uids).update(is_active=True)

        self.logger.info(differ.summary_label())

    @dry_runnable
    def handle(self, *args, data, force_update=False, **options):
        with (
            lock_timeout(10 * 60 * 1000),
            DataInclusionApiClient(
                global_constants.API_DATA_INCLUSION_BASE_URL,
                settings.API_DATA_INCLUSION_TOKEN,
            ) as di_client,
        ):
            if ArgumentData.REFERENCES in data:
                self.import_data_inclusion_reference_data(di_client)
                self.import_sources(di_client)

            if ArgumentData.STRUCTURES in data or ArgumentData.SERVICES in data:
                # `emplois-de-linclusion` is omitted, we already have the structures locally and no services yet.
                sources_except_emplois = sorted(
                    source["slug"] for source in di_client.sources() if source["slug"] != "emplois-de-linclusion"
                )

            if ArgumentData.STRUCTURES in data:
                self.import_structures(di_client, sources_except_emplois, force_update=force_update)

            if ArgumentData.SERVICES in data:
                self.import_services(di_client, sources_except_emplois, force_update=force_update)
