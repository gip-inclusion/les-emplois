import datetime
import json
import random
import uuid
from functools import partial
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time
from itoutils.django.decoupage_administratif.models import Department, Region
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import (
    assertContains,
    assertNotContains,
    assertNumQueries,
    assertQuerySetEqual,
    assertTemplateUsed,
)

from itou.companies.models import CompanyMembership
from itou.insertion.enums import BeneficiaryContactPreference, MobilizationEventKind, OrientationStatus
from itou.insertion.models import (
    SOURCE_DORA_VALUE,
    GenericReferenceItemKind,
    GenericReferenceItemSource,
    MobilizationEvent,
)
from itou.job_applications.enums import SenderKind
from itou.prescribers.models import PrescriberMembership
from tests.companies.factories import CompanyMembershipFactory
from tests.insertion.factories import (
    GenericReferenceItemFactory,
    InPersonReceptionFactory,
    OrientationFactory,
    RemoteReceptionFactory,
    ServiceFactory,
    StructureFactory,
)
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import PAGINATION_PAGE_ONE_MARKUP, parse_response_to_soup, pretty_indented


class TestStructures:
    def get_structure_url(self, structure):
        return reverse("insertion_views:structure_card", kwargs={"structure_uid": structure.uid})

    def test_card_view_anonymous_renders_description_tab(self, client, snapshot):
        structure = StructureFactory(
            name="Structure test",
            description="Description de test",
            source=GenericReferenceItemFactory(
                source=GenericReferenceItemSource.DATA_INCLUSION,
                kind=GenericReferenceItemKind.SOURCE,
                value=SOURCE_DORA_VALUE,
            ),
            source_link=f"{settings.DORA_WWW_BASE_URL}/structures/structure-test",
        )
        with assertSnapshotQueries(snapshot):
            response = client.get(self.get_structure_url(structure))

        assert response.context["structure"] == structure
        assertTemplateUsed(response, "insertion/structure_card.html")
        assertContains(response, "Structure test")
        assertContains(response, "Présentation de la structure")
        assertContains(response, "Description de test")
        assertContains(
            response,
            f'<link rel="canonical" href="{settings.DORA_WWW_BASE_URL}/structures/structure-test">',
            html=True,
        )
        assertContains(
            response,
            """
            <button class="btn btn-secondary btn-block listen-for-mobilization-event"
                    type="button"
                    data-bs-toggle="modal"
                    data-bs-target="#structure-contact-modal"
                    data-emplois-mobilization-kind="structure_contact"
                    data-matomo-event="true" data-matomo-category="fiche-structure" data-matomo-action="clic"
                    data-matomo-option="voir-coordonnees-structure">
                Voir les coordonnées de la structure
            </button>
           """,
            html=True,
        )
        assertContains(response, f'body.set("structure_uid", "{structure.uid}");')

    def test_card_view_non_dora_source_has_no_canonical(self, client):
        structure = StructureFactory(
            source=GenericReferenceItemFactory(
                source=GenericReferenceItemSource.DATA_INCLUSION,
                kind=GenericReferenceItemKind.SOURCE,
                value="other",
            ),
            source_link="https://example.com/structures/structure-test",
        )
        response = client.get(self.get_structure_url(structure))

        assertNotContains(response, 'rel="canonical"', html=True)

    def test_card_view_not_found(self, client):
        response = client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": "unknown-uid"}))

        assert response.status_code == 404

    def test_card_view_contact_modal_contains_structure_coordinates(self, client, snapshot):
        structure = StructureFactory(
            email="contact@structure.test",
            phone="+33102030405",
            address_line_1="10 rue de la Paix",
            post_code="75002",
            city="Paris",
            website="https://structure.test",
            opening_hours="Mo-Fr 08:30-12:30 open; PH off",
        )
        response = client.get(self.get_structure_url(structure))

        modal = parse_response_to_soup(response, selector="#structure-contact-modal")
        assert pretty_indented(modal) == snapshot

    def test_card_view_contact_modal_with_opening_hours(self, client):
        opening_hours = """Mo 09:00-12:00,14:00-17:30"Sans rendez-vous";Tu 09:00-12:00,14:00-17:30;
        We 09:00-12:00,14:00-17:30;Th 09:00-12:00,14:00-17:30;Fr 09:00-12:00,14:00-17:30; PH off"""
        structure = StructureFactory(
            opening_hours=opening_hours,
        )
        response = client.get(self.get_structure_url(structure))

        assertContains(
            response,
            (
                "Lun: 9h00 à 12h00 - 14h00 à 17h30 (Sans rendez-vous) "
                "• Mar: 9h00 à 12h00 - 14h00 à 17h30 • Mer: 9h00 à 12h00 - 14h00 à 17h30 "
                "• Jeu: 9h00 à 12h00 - 14h00 à 17h30 • Ven: 9h00 à 12h00 - 14h00 à 17h30 (Hors jours fériés)"
            ),
        )

    def test_card_view_renders_bootstrap_tabs_with_full_payload(self, client, snapshot):
        structure = StructureFactory(
            uid="structure-uid", name="Structure test", description="Description of test structure"
        )

        services = []
        for i in range(3):
            service = ServiceFactory(structure=structure, name=f"Test service {i}", uid=f"service-uid-{i}")
            services.append(service)

        with patch(
            "itou.www.insertion_views.views.bulk_load_division_labels",
            return_value=["Perimeter 1", "Perimeter 2", "Perimeter 3"],
        ):
            response = client.get(self.get_structure_url(structure))

        assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot

    def test_card_view_services_link_to_service_detail(self, client):
        structure = StructureFactory()
        service = ServiceFactory(structure=structure)

        response = client.get(self.get_structure_url(structure))

        service_url = reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid})
        structure_url = reverse("insertion_views:structure_card", kwargs={"structure_uid": structure.uid})
        expected_href = f"{service_url}?back_url={structure_url}%23structure-services"

        assertContains(response, f'href="{expected_href}"')

    def test_card_view_loads_service_perimeters_without_n_plus_one(self, client):
        Region.objects.create(code="53", name="Bretagne")
        for code, name in [("29", "Finistère"), ("56", "Morbihan"), ("35", "Ille-et-Vilaine")]:
            Department.objects.create(code=code, name=name, region="53")

        structure = StructureFactory()
        for name, code in [("Service A", "29"), ("Service B", "56"), ("Service C", "35")]:
            ServiceFactory(structure=structure, name=name, eligibility_zones=[code])

        with assertNumQueries(
            1  # structure + source
            + 1  # services prefetch
            + 1  # service receptions prefetch
            + 1  # departments bulk (eligibility_zones)
            + 1  # cities bulk (eligibility_zones)
            + 1  # epcis bulk (eligibility_zones)
            + 2  # django session (needed for csrf_token)
            + 2  # savepoint
        ):
            response = client.get(self.get_structure_url(structure))

        assert response.status_code == 200
        perimeters = [service.perimeter for service in response.context["services"]]
        assert perimeters == ["Finistère", "Morbihan", "Ille-et-Vilaine"]
        assertContains(response, "Périmètre : Finistère")
        assertContains(response, "Périmètre : Morbihan")
        assertContains(response, "Périmètre : Ille-et-Vilaine")

    def test_card_view_services_display_reception_location(self, client):
        structure = StructureFactory()
        ServiceFactory(
            structure=structure,
            name="Service Poitiers",
            city="Poitiers",
            receptions=[InPersonReceptionFactory()],
        )
        ServiceFactory(
            structure=structure,
            name="Service Loudun",
            city="Loudun",
            receptions=[InPersonReceptionFactory()],
        )
        ServiceFactory(
            structure=structure,
            name="Service à distance",
            receptions=[RemoteReceptionFactory()],
        )

        response = client.get(self.get_structure_url(structure))

        assertContains(response, "Lieu d'accueil : Poitiers")
        assertContains(response, "Lieu d'accueil : Loudun")
        assertContains(response, "Lieu d'accueil : à distance")

    def test_no_error_when_special_chars_in_uid(self, client):
        structure = StructureFactory()
        service = ServiceFactory(structure=structure, uid="fredo--97416_13643-activités / ateliers")  # real case

        response = client.get(self.get_structure_url(structure))
        assertContains(response, reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid}))

    @pytest.mark.parametrize(
        "user_factory,assertion",
        [
            (None, assertContains),
            (JobSeekerFactory, assertNotContains),
            (partial(PrescriberFactory, membership=True), assertContains),
            (partial(EmployerFactory, membership=True), assertContains),
            (partial(LaborInspectorFactory, membership=True), assertNotContains),
            (ItouStaffFactory, assertNotContains),
        ],
    )
    def test_card_view_register_mobilization_event_per_user_kind(self, client, user_factory, assertion):
        structure = StructureFactory(
            name="Structure test",
            description="Description de test",
            source=GenericReferenceItemFactory(
                source=GenericReferenceItemSource.DATA_INCLUSION,
                kind=GenericReferenceItemKind.SOURCE,
                value=SOURCE_DORA_VALUE,
            ),
            source_link=f"{settings.DORA_WWW_BASE_URL}/structures/structure-test",
        )
        if user_factory:
            client.force_login(user_factory())
        response = client.get(self.get_structure_url(structure))

        assertion(response, f'body.set("structure_uid", "{structure.uid}");')


class TestServices:
    LOGIN_URL = reverse("login:existing_user")
    ORIENT_BTN_LABEL = "Orienter un bénéficiaire"
    DISPLAY_SERVICE_CONTACT_BTN = """
    <button class="btn btn-lg btn-outline-white btn-block justify-content-center" type="button" data-bs-toggle="modal"
            data-bs-target="#service-contact-modal" data-emplois-mobilization-kind="service_contact"
            data-matomo-event="true" data-matomo-category="fiche-service" data-matomo-action="clic"
            data-matomo-option="voir-coordonnees-contact">
        Voir les coordonnées de contact du service
    </button>"""
    DISPLAY_SERVICE_CONTACT_JS = 'body.set("service_uid", "%s");'
    FORMS_TO_FILL = "Documents à compléter"

    def get_service_url(self, service):
        return reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid})

    def get_nexus_auto_login_url(self, service_url):
        return reverse("nexus:auto_login", query={"next_url": service_url})

    def test_detail_accessible_without_login(self, client):
        service = ServiceFactory(
            uid="test-service-uid",
            name="Mon service de test",
            updated_on="2025-01-15",
            source__value="dora",
            source__label="Dora",
            structure__uid="test-structure-uid",
            structure__name="Ma structure de test",
            structure__updated_on="2025-01-15",
        )
        response = client.get(self.get_service_url(service))
        assert response.status_code == 200

    def test_detail_opening_hours_with_comments(self, client):
        service = ServiceFactory(
            uid="test-service-uid",
            name="Mon service de test",
            updated_on="2025-01-15",
            source__value="other",
            source__label="Other",
            opening_hours="Mo-Fr 07:45-18:30 open; Sa open; Aug closed; Dec 25-Jan 1 closed",
            structure__uid="test-structure-uid",
            structure__name="Ma structure de test",
            structure__updated_on="2025-01-15",
        )
        response = client.get(self.get_service_url(service))
        assert response.status_code == 200
        formatted_opening_hours = response.context["formatted_opening_hours"]
        hours = {e["label"]: e["hours"] for e in formatted_opening_hours["entries"]}
        assert hours["Lundi"] == "7h45 à 18h30"
        assert hours["Samedi"] == "ouvert"
        assert formatted_opening_hours["comments"] == ["Fermé en août", "Fermé du 25 décembre au 1er janvier"]
        assertContains(response, "Fermé en août.")
        assertContains(response, "Fermé du 25 décembre au 1er janvier.")

    def test_detail_basic_dora(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        service = ServiceFactory(
            uid="test-service-uid",
            name="Mon service de test",
            updated_on="2025-01-15",
            source__value="dora",
            source__label="Dora",
            source_link="https://dora.inclusion.gouv.fr/services/test-service-uid",
            # dora-only fields — should appear
            access_conditions_dora=["Avoir plus de 18 ans", "Résider en France"],
            credentials=["Pièce d'identité en cours de validité"],
            # DI-only field — should NOT appear
            access_conditions_di="Ne doit pas apparaître pour dora",
            structure__uid="test-structure-uid",
            structure__name="Ma structure de test",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assert response.status_code == 200
        assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot

    def test_detail_basic_not_dora(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        service = ServiceFactory(
            uid="test-service-uid",
            name="Mon service de test",
            updated_on="2025-01-15",
            source__value="other",
            source__label="Other",
            # DI-only field — should appear
            access_conditions_di="Être orienté par un prescripteur\\nAvoir 18 ans",
            # dora-only fields — should NOT appear
            mobilization_modes_professionals_other="Ne doit pas apparaître pour data·inclusion",
            access_conditions_dora=["Ne doit pas apparaître pour data·inclusion"],
            credentials=["Ne doit pas apparaître pour data·inclusion"],
            structure__uid="test-structure-uid",
            structure__name="Ma structure de test",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assert response.status_code == 200
        assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot

    def test_detail_with_all_optional_fields(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        source = GenericReferenceItemFactory(kind=GenericReferenceItemKind.SOURCE, value="dora", label="Dora")
        fee = GenericReferenceItemFactory(kind=GenericReferenceItemKind.FEE, value="gratuit", label="Gratuit")
        public = GenericReferenceItemFactory(kind=GenericReferenceItemKind.PUBLIC, value="adultes", label="Adultes")
        reception = GenericReferenceItemFactory(
            kind=GenericReferenceItemKind.RECEPTION, value="en-presentiel", label="En présentiel"
        )
        thematic = GenericReferenceItemFactory(
            kind=GenericReferenceItemKind.THEMATIC,
            value="logement-hebergement--louer-un-logement",
            label="Louer un logement",
        )
        mobilization = GenericReferenceItemFactory(
            kind=GenericReferenceItemKind.MOBILIZATION, value="telephonique", label="Par téléphone"
        )

        service = ServiceFactory(
            uid="test-service-full-uid",
            name="Service complet",
            updated_on="2025-06-01",
            description="## Description complète\n\nAvec du **markdown**.",
            description_short="Résumé court du service.",
            source=source,
            source_link="https://dora.inclusion.gouv.fr/services/test",
            fee=fee,
            fee_details="Sous conditions de ressources.",
            publics_details="Toute personne majeure.",
            access_conditions_dora=["Être orienté par un prescripteur."],
            mobilizations_details="Contacter le service par téléphone.",
            contact_email="contact@service.fr",
            contact_phone="01 23 45 67 89",
            is_orientable_with_form=True,
            average_orientation_response_delay_days=3,
            opening_hours="Mo-Fr 09:00-17:00; PH off",
            address_line_1="12 rue de la Paix",
            address_line_2="Bâtiment B",
            post_code="75001",
            city="Paris",
            structure__uid="test-structure-full-uid",
            structure__name="Structure complète",
            structure__updated_on="2025-06-01",
            thematics=[],
            receptions=[],
        )
        service.publics.add(public)
        service.receptions.add(reception)
        service.thematics.add(thematic)
        service.mobilizations.add(mobilization)

        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assert response.status_code == 200
        assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot

    def test_detail_with_external_orientation_link(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        test_link = "https://test.example.com"
        service = ServiceFactory(
            uid="test-external-uid",
            name="Service avec lien externe",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            mobilization_modes_professionals_external_form_link="https://test.example.com",
            mobilization_modes_professionals_external_form_link_text="Test link",
            structure__uid="test-structure-external-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, "Test link")
        assertContains(response, f'href="{test_link}"')
        assert pretty_indented(parse_response_to_soup(response, ".c-box--action")) == snapshot

    def test_detail_with_external_orientation_link_without_text(self, client):
        user = PrescriberFactory(membership=True)
        external_link = "https://test.example.com"
        service = ServiceFactory(
            uid="test-external-no-text-uid",
            name="Service avec lien externe sans intitulé",
            updated_on="2025-01-15",
            is_orientable_with_form=False,
            mobilization_modes_professionals_external_form_link=external_link,
            mobilization_modes_professionals_external_form_link_text="",
            structure__uid="test-structure-external-no-text-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, self.ORIENT_BTN_LABEL)
        assertContains(response, f'href="{external_link}"')

    def test_di_service_orientable_with_external_link_prefers_link(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        external_link = "https://test.example.com"
        service = ServiceFactory(
            uid="test-orientable-ext-uid",
            name="DI service orientable avec lien externe",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            mobilization_modes_professionals_external_form_link=external_link,
            mobilization_modes_professionals_external_form_link_text="Lien externe",
            structure__uid="test-structure-orientable-ext-uid",
            structure__updated_on="2025-01-15",
        )

        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, f'href="{external_link}"')
        assertNotContains(response, reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid}))
        assert pretty_indented(parse_response_to_soup(response, ".c-box--action")) == snapshot

    def test_dora_service_orientable_with_form_and_external_link_prefers_wizard(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        external_link = "https://test.example.com"
        service = ServiceFactory(
            uid="test-orientable-ext-uid",
            name="Dora service orientable avec lien externe",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            mobilization_modes_professionals_external_form_link=external_link,
            mobilization_modes_professionals_external_form_link_text="Lien externe",
            structure__uid="test-structure-orientable-ext-uid",
            structure__updated_on="2025-01-15",
            source__value="dora",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid}))
        assert pretty_indented(parse_response_to_soup(response, ".c-box--action")) == snapshot

    def test_dora_service_not_orientable_with_form_prefers_external_link(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        external_link = "https://test.example.com"
        service = ServiceFactory(
            uid="test-orientable-ext-uid",
            name="Dora service pas orientable avec le formulaire qui a un lien externe",
            updated_on="2025-01-15",
            is_orientable_with_form=False,
            mobilization_modes_professionals_external_form_link=external_link,
            mobilization_modes_professionals_external_form_link_text="Lien externe",
            structure__uid="test-structure-orientable-ext-uid",
            structure__updated_on="2025-01-15",
            source__value="dora",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, f'href="{external_link}"')
        assertNotContains(response, reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid}))
        assert pretty_indented(parse_response_to_soup(response, ".c-box--action")) == snapshot

    def test_detail_orientable_and_user_authenticated(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        service = ServiceFactory(
            uid="test-orientable-uid",
            name="Service orientable",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            structure__uid="test-structure-orientable-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, self.ORIENT_BTN_LABEL)
        assert pretty_indented(parse_response_to_soup(response, ".c-box--action")) == snapshot

    def test_detail_orientable_and_job_seeker_authenticated(self, client):
        user = JobSeekerFactory()
        service = ServiceFactory(
            uid="test-orientable-job-seeker-uid",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            structure__uid="test-structure-orientable-job-seeker-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, self.ORIENT_BTN_LABEL)
        assertNotContains(
            response,
            reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid}),
        )
        assertNotContains(response, "c-box--action")
        assertNotContains(response, "Informations de contact non renseignées")

    def test_detail_orientable_and_user_not_authenticated(self, client):
        service = ServiceFactory(
            uid="test-orientable-uid",
            name="Service orientable",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            structure__uid="test-structure-orientable-uid",
            structure__updated_on="2025-01-15",
        )

        service_url = self.get_service_url(service)
        response = client.get(service_url)
        assertContains(response, f'href="{self.LOGIN_URL}?next={service_url}"')

    def test_detail_not_orientable(self, client, snapshot):
        user = PrescriberFactory(membership=True)
        service = ServiceFactory(
            uid="test-not-orientable-uid",
            name="Service non orientable",
            updated_on="2025-01-15",
            is_orientable_with_form=False,
            structure__uid="test-structure-not-orientable-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, self.ORIENT_BTN_LABEL)
        assert pretty_indented(parse_response_to_soup(response, ".c-box--action")) == snapshot

    def test_detail_non_orientable_di_sources(self, client, settings):
        user = PrescriberFactory(membership=True)
        blacklisted_source = "blacklisted-source"
        settings.NON_ORIENTABLE_DI_SOURCES = [blacklisted_source]
        service = ServiceFactory(
            uid="test-orientable-uid",
            name="Service non orientable",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            source__value=blacklisted_source,
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, self.ORIENT_BTN_LABEL)

    def test_detail_non_orientable_di_sources_with_external_link(self, client, settings):
        user = PrescriberFactory(membership=True)
        blacklisted_source = "blacklisted-source"
        settings.NON_ORIENTABLE_DI_SOURCES = [blacklisted_source]
        external_link = "https://test.example.com"
        service = ServiceFactory(
            uid="test-orientable-uid",
            name="Service non orientable",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            mobilization_modes_professionals_external_form_link=external_link,
            mobilization_modes_professionals_external_form_link_text="",
            source__value=blacklisted_source,
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, self.ORIENT_BTN_LABEL)
        assertContains(response, f'href="{external_link}"')

    def test_detail_contact_section_hidden_without_contact_info(self, client):
        user = PrescriberFactory(membership=True)
        service = ServiceFactory(
            uid="test-no-contact-uid",
            updated_on="2025-01-15",
            is_orientable_with_form=False,
            contact_full_name="",
            contact_email="",
            contact_phone="",
            structure__uid="test-structure-no-contact-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, "Voir les coordonnées de contact du service")
        assertContains(response, "Informations de contact non renseignées")

    def test_detail_contact_button_shown_when_authenticated(self, client):
        user = PrescriberFactory(membership=True)
        service = ServiceFactory(
            uid="test-contact-auth-uid",
            updated_on="2025-01-15",
            contact_email="contact@example.com",
            contact_is_public=False,
            structure__uid="test-structure-contact-auth-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, self.DISPLAY_SERVICE_CONTACT_BTN, html=True)
        assertContains(response, self.DISPLAY_SERVICE_CONTACT_JS % service.uid)
        assertContains(response, "contact@example.com")

    def test_detail_contact_button_shown_when_public(self, client):
        service = ServiceFactory(
            uid="test-contact-public-uid",
            updated_on="2025-01-15",
            contact_email="contact@example.com",
            contact_is_public=True,
            structure__uid="test-structure-contact-public-uid",
            structure__updated_on="2025-01-15",
        )
        response = client.get(self.get_service_url(service))
        assertContains(response, self.DISPLAY_SERVICE_CONTACT_BTN, html=True)
        assertContains(response, self.DISPLAY_SERVICE_CONTACT_JS % service.uid)
        assertContains(response, "contact@example.com")

    def test_detail_contact_login_link_shown_when_anonymous_and_not_public(self, client):
        service = ServiceFactory(
            uid="test-contact-private-uid",
            updated_on="2025-01-15",
            contact_email="contact@example.com",
            contact_is_public=False,
            structure__uid="test-structure-contact-private-uid",
            structure__updated_on="2025-01-15",
        )
        service_url = self.get_service_url(service)
        response = client.get(service_url)
        assertContains(response, f'href="{self.LOGIN_URL}?next={service_url}"')
        assertNotContains(response, self.DISPLAY_SERVICE_CONTACT_BTN, html=True)
        assertContains(response, self.DISPLAY_SERVICE_CONTACT_JS % service.uid)
        assertNotContains(response, "contact@example.com")

    def test_detail_with_source_link(self, client):
        user = PrescriberFactory(membership=True)
        service_with_link = ServiceFactory(
            uid="test-with-link-uid",
            source__value="dora",
            source_link="https://dora.inclusion.gouv.fr/services/test",
            updated_on="2025-01-15",
            structure__uid="test-structure-with-link-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service_with_link))
        assertContains(response, '<link rel="canonical" href="https://dora.inclusion.gouv.fr/services/test">')

    def test_detail_without_source_link(self, client):
        user = PrescriberFactory(membership=True)
        service_no_link = ServiceFactory(
            uid="test-no-link-uid",
            source_link="",
            updated_on="2025-01-15",
            structure__uid="test-structure-no-link-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service_no_link))
        assertNotContains(response, 'rel="canonical"')

    def test_detail_orientation_url_points_to_wizard_start(self, client):
        user = PrescriberFactory(membership=True)
        service = ServiceFactory(
            uid="test-wizard-uid",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            structure__uid="test-structure-wizard-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)

        response = client.get(self.get_service_url(service))

        assert response.status_code == 200
        action_box = str(parse_response_to_soup(response, ".c-box--action"))
        wizard_url = reverse("insertion_views:start_orientation", kwargs={"service_uid": service.uid})
        assert wizard_url in action_box
        assert reverse("nexus:auto_login") not in action_box

    def test_detail_credential_documents_empty(self, client):
        service = ServiceFactory(
            uid="test-creds-empty-uid",
            updated_on="2025-01-15",
            credentials_documents=[],
            structure__uid="test-structure-creds-empty-uid",
            structure__updated_on="2025-01-15",
        )
        response = client.get(self.get_service_url(service))
        assert response.status_code == 200
        assert response.context["credential_documents"] == []
        assertNotContains(response, self.FORMS_TO_FILL)

    def test_detail_credential_documents(self, client, snapshot):
        service = ServiceFactory(
            uid="test-creds-uid",
            updated_on="2025-01-15",
            credentials_documents=["folder/sub/my_form.pdf", "other/justificatif.docx"],
            structure__uid="test-structure-creds-uid",
            structure__updated_on="2025-01-15",
        )
        s3_urls = [
            "https://s3.example.com/my_form.pdf?token=aaa",
            "https://s3.example.com/justificatif.docx?token=bbb",
        ]
        with patch(
            "itou.insertion.models.generate_dora_storage_url",
            side_effect=s3_urls,
        ):
            response = client.get(self.get_service_url(service))

        assertContains(response, self.FORMS_TO_FILL)
        assert response.context["credential_documents"] == [
            ("my_form.pdf", "https://s3.example.com/my_form.pdf?token=aaa"),
            ("justificatif.docx", "https://s3.example.com/justificatif.docx?token=bbb"),
        ]
        assert pretty_indented(parse_response_to_soup(response, "#credentials-documents")) == snapshot

    def test_format_categories_no_thematics(self, client):
        service = ServiceFactory(
            uid="test-categories-uid",
            updated_on="2025-01-15",
            structure__uid="test-structure-categories-uid",
            structure__updated_on="2025-01-15",
            thematics=[],
        )
        response = client.get(self.get_service_url(service))
        assert response.context["formatted_categories"] == []

    def test_format_categories_single_thematic(self, client):
        thematic = GenericReferenceItemFactory(
            kind=GenericReferenceItemKind.THEMATIC,
            value="choisir-un-metier--explorer-des-metiers",
            label="Explorer des métiers",
        )
        service = ServiceFactory(
            uid="test-categories-uid",
            updated_on="2025-01-15",
            structure__uid="test-structure-categories-uid",
            structure__updated_on="2025-01-15",
            thematics=[],
        )
        service.thematics.add(thematic)
        response = client.get(self.get_service_url(service))
        assert response.context["formatted_categories"] == [("Choisir un métier", "Explorer des métiers")]

    def test_format_categories_multiple_categories(self, client):
        thematic_a = GenericReferenceItemFactory(
            kind=GenericReferenceItemKind.THEMATIC,
            value="choisir-un-metier--explorer-des-metiers",
            label="Explorer des métiers",
        )
        thematic_b = GenericReferenceItemFactory(
            kind=GenericReferenceItemKind.THEMATIC,
            value="creer-une-entreprise--definir-son-projet",
            label="Définir son projet",
        )
        service = ServiceFactory(
            uid="test-categories-uid",
            updated_on="2025-01-15",
            structure__uid="test-structure-categories-uid",
            structure__updated_on="2025-01-15",
            thematics=[],
        )
        service.thematics.add(thematic_a, thematic_b)
        response = client.get(self.get_service_url(service))
        assert sorted(response.context["formatted_categories"]) == [
            ("Choisir un métier", "Explorer des métiers"),
            ("Créer une entreprise", "Définir son projet"),
        ]

    # --- Mobilization modes: 'autre' handling ---

    def test_professionals_has_autre_true_when_autre_mode_selected(self, client):
        mode = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            value="autre",
            label="Autre",
        )
        service = ServiceFactory(
            uid="prof-autre-true",
            updated_on="2025-01-15",
            source__value="dora",
            structure__uid="structure-prof-autre-true",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_professionals.add(mode)
        response = client.get(self.get_service_url(service))
        assert response.context["professionals_has_autre"] is True

    def test_professionals_has_autre_false_without_autre_mode(self, client):
        mode = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            value="telephonique",
            label="Par téléphone",
        )
        service = ServiceFactory(
            uid="prof-autre-false",
            updated_on="2025-01-15",
            source__value="dora",
            structure__uid="structure-prof-autre-false",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_professionals.add(mode)
        response = client.get(self.get_service_url(service))
        assert response.context["professionals_has_autre"] is False

    def test_beneficiaries_has_autre_true_when_autre_mode_selected(self, client):
        mode = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
            value="autre",
            label="Autre",
        )
        service = ServiceFactory(
            uid="ben-autre-true",
            updated_on="2025-01-15",
            source__value="dora",
            structure__uid="structure-ben-autre-true",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_beneficiaries.add(mode)
        response = client.get(self.get_service_url(service))
        assert response.context["beneficiaries_has_autre"] is True

    def test_beneficiaries_has_autre_false_without_autre_mode(self, client):
        mode = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
            value="en-presentiel",
            label="En présentiel",
        )
        service = ServiceFactory(
            uid="ben-autre-false",
            updated_on="2025-01-15",
            source__value="dora",
            structure__uid="structure-ben-autre-false",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_beneficiaries.add(mode)
        response = client.get(self.get_service_url(service))
        assert response.context["beneficiaries_has_autre"] is False

    def test_autre_mode_label_not_rendered_in_list(self, client):
        mode_autre = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            value="autre",
            label="Autre (ne doit pas apparaître)",
        )
        mode_phone = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            value="telephonique",
            label="Par téléphone",
        )
        service = ServiceFactory(
            uid="autre-not-in-list",
            updated_on="2025-01-15",
            source__value="dora",
            mobilization_modes_professionals_other="Contacter par courrier",
            structure__uid="structure-autre-not-in-list",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_professionals.add(mode_autre, mode_phone)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, "Autre (ne doit pas apparaître)")
        assertContains(response, "Par téléphone")
        assertContains(response, "Contacter par courrier")

    def test_other_field_shown_when_autre_mode_selected(self, client):
        mode_autre = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            value="autre",
            label="Autre",
        )
        service = ServiceFactory(
            uid="other-shown-with-autre",
            updated_on="2025-01-15",
            source__value="dora",
            mobilization_modes_professionals_other="Contacter le service par email",
            structure__uid="structure-other-shown-with-autre",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_professionals.add(mode_autre)
        response = client.get(self.get_service_url(service))
        assertContains(response, "Contacter le service par email")

    def test_other_field_not_shown_without_autre_mode(self, client):
        mode_phone = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            value="telephonique",
            label="Par téléphone",
        )
        service = ServiceFactory(
            uid="other-hidden-no-autre",
            updated_on="2025-01-15",
            source__value="dora",
            mobilization_modes_professionals_other="Ce texte ne doit pas apparaître",
            structure__uid="structure-other-hidden-no-autre",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_professionals.add(mode_phone)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, "Ce texte ne doit pas apparaître")

    def test_beneficiaries_autre_mode_label_not_rendered_in_list(self, client):
        mode_autre = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
            value="autre",
            label="Autre (bénéficiaire ne doit pas apparaître)",
        )
        mode_presentiel = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
            value="en-presentiel",
            label="En présentiel",
        )
        service = ServiceFactory(
            uid="ben-autre-not-in-list",
            updated_on="2025-01-15",
            source__value="dora",
            mobilization_modes_beneficiaries_other="Prise en charge specifique",
            structure__uid="structure-ben-autre-not-in-list",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_beneficiaries.add(mode_autre, mode_presentiel)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, "Autre (bénéficiaire ne doit pas apparaître)")
        assertContains(response, "En présentiel")
        assertContains(response, "Prise en charge specifique")

    def test_beneficiaries_other_field_not_shown_without_autre_mode(self, client):
        mode_presentiel = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
            value="en-presentiel",
            label="En présentiel",
        )
        service = ServiceFactory(
            uid="ben-other-hidden",
            updated_on="2025-01-15",
            source__value="dora",
            mobilization_modes_beneficiaries_other="Ce texte beneficiaire ne doit pas apparaitre",
            structure__uid="structure-ben-other-hidden",
            structure__updated_on="2025-01-15",
        )
        service.mobilization_modes_beneficiaries.add(mode_presentiel)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, "Ce texte beneficiaire ne doit pas apparaitre")

    def test_change_name_of_via_formulaire_dora_mobilization_mode(self, client):
        dora_form_mobilization_mode = GenericReferenceItemFactory(
            source=GenericReferenceItemSource.DORA,
            kind=GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
            value="formulaire-dora",
            label="Via le formulaire DORA",
        )

        service = ServiceFactory(source__value="dora")

        service.mobilization_modes_professionals.add(dora_form_mobilization_mode)

        response = client.get(self.get_service_url(service))
        assertNotContains(response, "Via le formulaire DORA")
        assertContains(response, "Via le formulaire (bouton “Orienter votre bénéficiaire”)")

    @pytest.mark.parametrize(
        "user_factory,assertion",
        [
            (None, assertContains),
            (JobSeekerFactory, assertNotContains),
            (partial(PrescriberFactory, membership=True), assertContains),
            (partial(EmployerFactory, membership=True), assertContains),
            (partial(LaborInspectorFactory, membership=True), assertNotContains),
            (ItouStaffFactory, assertNotContains),
        ],
    )
    def test_card_view_register_mobilization_event_per_user_kind(self, client, user_factory, assertion):
        service = ServiceFactory(
            contact_email="contact@example.com",
            contact_is_public=True,
        )
        if user_factory:
            client.force_login(user_factory())
        response = client.get(self.get_service_url(service))

        assertion(response, f'body.set("service_uid", "{service.uid}");')


class TestOrientationDetails:
    def get_orientation_url(self, orientation):
        return reverse("insertion_views:orientation_details", kwargs={"orientation_id": orientation.id})

    def get_job_seeker_details_url(self, job_seeker):
        return reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id})

    @freeze_time("2026-07-24")
    def test_detail_basic_dora(self, client, snapshot):
        service = ServiceFactory(
            uid="source--service",
            name="S’hair vice",
            updated_on="2025-01-15",
            source__value="dora",
            source__label="Dora",
            source_link="https://domain.fake/services/test-service-uid",
            # dora-only fields — should appear
            access_conditions_dora=["Avoir plus de 18 ans", "Résider en France"],
            credentials=["Pièce d'identité en cours de validité"],
            # DI-only field — should NOT appear
            access_conditions_di="Ne doit pas apparaître pour dora",
            structure__name="Gonflable",
            structure__uid="structure-uid",
        )

        membership = PrescriberMembershipFactory(organization__authorized=True)
        user = membership.user
        organization = membership.organization

        beneficiary = JobSeekerFactory(for_snapshot=True)

        orientation = OrientationFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            beneficiary=beneficiary,
            sender=user,
            sender_prescriber_organization=organization,
            sender_kind=SenderKind.PRESCRIBER,
            service=service,
        )

        client.force_login(user)

        with assertSnapshotQueries(snapshot(name="queries")):
            response = client.get(self.get_orientation_url(orientation))

        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot(name="page")
        assertContains(response, self.get_job_seeker_details_url(beneficiary))

    @freeze_time("2026-07-24")
    def test_detail_basic_not_dora(self, client, snapshot):
        service = ServiceFactory(
            uid="source--service",
            name="S’hair vice",
            updated_on="2025-01-15",
            source__value="other",
            source__label="Other",
            # DI-only field — should appear
            access_conditions_di="Être orienté par un prescripteur\\nAvoir 18 ans",
            # dora-only fields — should NOT appear
            access_conditions_dora=["Ne doit pas apparaître pour data·inclusion"],
            credentials=["Ne doit pas apparaître pour data·inclusion"],
            structure__name="Gonflable",
            structure__uid="structure-uid",
        )

        membership = PrescriberMembershipFactory(organization__authorized=True)
        user = membership.user
        organization = membership.organization

        beneficiary = JobSeekerFactory(for_snapshot=True)

        orientation = OrientationFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            beneficiary=beneficiary,
            sender=user,
            sender_prescriber_organization=organization,
            sender_kind=SenderKind.PRESCRIBER,
            service=service,
        )

        client.force_login(user)
        response = client.get(self.get_orientation_url(orientation))

        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot(name="page")
        assertContains(response, self.get_job_seeker_details_url(beneficiary))

    @freeze_time("2026-07-24")
    def test_detail_with_all_fields_dora(self, client, snapshot):
        service = ServiceFactory(
            uid="test-service-full-uid",
            name="Service complet",
            updated_on="2025-06-01",
            source__value="dora",
            access_conditions_dora=["Être orienté par un prescripteur."],
            mobilizations_details="Contacter le service par téléphone.",
            contact_email="contact@service.fr",
            contact_phone="01 23 45 67 89",
            structure__name="Structure complète",
            structure__uid="structure-uid",
        )
        beneficiary = JobSeekerFactory(for_snapshot=True)

        for membership_factory in [
            partial(PrescriberMembershipFactory, organization__authorized=True),
            CompanyMembershipFactory,
        ]:
            # Output should be the same for prescribers and employers
            membership = membership_factory()
            user = membership.user
            organization = membership.organization if isinstance(membership, PrescriberMembership) else None
            company = membership.company if isinstance(membership, CompanyMembership) else None

            orientation = OrientationFactory(
                id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
                beneficiary=beneficiary,
                sender=user,
                sender_prescriber_organization=organization,
                sender_company=company,
                sender_kind=SenderKind.PRESCRIBER if organization else SenderKind.EMPLOYER,
                service=service,
                beneficiary_contact_preferences=[
                    BeneficiaryContactPreference.EMAIL,
                    BeneficiaryContactPreference.PHONE,
                    BeneficiaryContactPreference.OTHER,
                ],
                beneficiary_other_contact_method="courrier postal",
                beneficiary_availability=datetime.date(2026, 7, 31),
                requirements=["NonAffiché"],
                situation=["NonAffiché"],
                situation_other="NonAffiché",
                referent_last_name="NonAffiché",
                referent_first_name="NonAffiché",
                referent_email="NonAffiché",
                referent_phone="NonAffiché",
                orientation_reasons="Pour améliorer l’embauchabilité de cette bénéficiaire.",
                status=OrientationStatus.ACCEPTED,
                processing_date=datetime.datetime(2099, 12, 31, 23, 59, tzinfo=datetime.UTC),  # not displayed
                duration_weekly_hours=5,
                duration_weeks=8,
                data_protection_commitment=False,  # not displayed
                attachments=[
                    "staging/#orientations/7d6dnkQ2E4bz7slKI5mKOnJG15PYQRtQ/cv.pdf",
                ],
            )

            client.force_login(user)
            response = client.get(self.get_orientation_url(orientation))

            assert pretty_indented(
                parse_response_to_soup(
                    response,
                    selector="#main",
                    replace_in_attr=[("href", orientation.attachments_details[0][1], "[computed URL of attachment]")],
                )
            ) == snapshot(name="page")
            assertNotContains(response, "NonAffiché")

            orientation.delete()

    @pytest.mark.parametrize(
        "user_factory,status_code",
        [
            (ItouStaffFactory, 403),
            (JobSeekerFactory, 403),
            (partial(LaborInspectorFactory, membership=True), 403),
            (partial(PrescriberFactory, membership=True), 404),  # authorized but not in the the sender org
            (partial(EmployerFactory, membership=True), 404),  # authorized but not in the sender org
        ],
    )
    def test_no_access(self, client, user_factory, status_code):
        orientation = OrientationFactory()
        client.force_login(user_factory())
        response = client.get(self.get_orientation_url(orientation))
        assert response.status_code == status_code

    def test_access_members_of_sender_prescriber_org(self, client):
        membership = PrescriberMembershipFactory()
        user = membership.user
        organization = membership.organization
        other_user = PrescriberMembershipFactory(organization=organization).user

        orientation = OrientationFactory(
            sender=other_user, sender_kind=SenderKind.PRESCRIBER, sender_prescriber_organization=organization
        )
        client.force_login(user)
        response = client.get(self.get_orientation_url(orientation))
        assertContains(response, orientation.service.name)

    def test_access_members_of_sender_company(self, client):
        membership = CompanyMembershipFactory()
        user = membership.user
        company = membership.company
        other_user = CompanyMembershipFactory(company=company).user

        orientation = OrientationFactory(
            sender=other_user,
            sender_kind=SenderKind.EMPLOYER,
            sender_prescriber_organization=None,
            sender_company=company,
        )
        client.force_login(user)
        response = client.get(self.get_orientation_url(orientation))
        assertContains(response, orientation.service.name)

    def test_non_authorized_prescriber_cannot_see_pii(self, client):
        service = ServiceFactory(
            uid="test-service-uid",
            name="Service complet",
            source__value="dora",
            access_conditions_dora=["Être orienté par un prescripteur."],
            mobilizations_details="Contacter le service par téléphone.",
        )

        membership = PrescriberMembershipFactory()
        user = membership.user
        organization = membership.organization

        beneficiary = JobSeekerFactory(
            first_name="Marimprobable",
            last_name="Astellrare",
            email="marimprobable.astell@email.fake",
            phone="0987654321",
        )

        orientation = OrientationFactory(
            beneficiary=beneficiary,
            sender=user,
            sender_prescriber_organization=organization,
            sender_kind=SenderKind.PRESCRIBER,
            service=service,
            orientation_reasons="Pour améliorer l’embauchabilité de cette bénéficiaire.",
        )

        client.force_login(user)
        response = client.get(self.get_orientation_url(orientation))

        assertNotContains(response, beneficiary.first_name)
        assertContains(response, "<strong>M…</strong>", html=True)
        assertNotContains(response, beneficiary.last_name)
        assertContains(response, "<strong>A…</strong>", html=True)
        assertNotContains(response, beneficiary.email)
        assertNotContains(response, beneficiary.phone)
        assertNotContains(response, self.get_job_seeker_details_url(beneficiary))

    @pytest.mark.parametrize("is_active, assertion", [(True, assertContains), (False, assertNotContains)])
    def test_hide_service_link_if_inactive(self, client, is_active, assertion):
        service = ServiceFactory(is_active=is_active)

        membership = PrescriberMembershipFactory(organization__authorized=True)
        user = membership.user
        organization = membership.organization

        orientation = OrientationFactory(
            sender=user,
            sender_prescriber_organization=organization,
            sender_kind=SenderKind.PRESCRIBER,
            service=service,
        )

        client.force_login(user)
        response = client.get(self.get_orientation_url(orientation))
        service_url = reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid})
        servce_button_markup = f"""<a href="{service_url}?back_url={self.get_orientation_url(orientation)}"
                                      class="btn btn-lg btn-secondary" data-matomo-event="true"
                                      data-matomo-category="orientation-detail" data-matomo-action="clic"
                                      data-matomo-option="voir-service">
                <span>Accéder au détail du service</span>
            </a>"""
        assertion(response, servce_button_markup, html=True)


class TestOrientationsList:
    LIST_URL = reverse("insertion_views:orientations_list")
    RESET_BTN_MARKUP = f"""
    <a href="{LIST_URL}" class="btn btn-ico btn-dropdown-filter" aria-label="Réinitialiser le filtre actif">
        <i class="ri-eraser-line fw-medium" aria-hidden="true"></i>
        <span>Effacer tout</span>
    </a>
    """

    @staticmethod
    def replace_attrs(soup, attrs, attrs_to_update, **find_all_kwargs):
        nodes = soup.find_all(attrs=attrs, **find_all_kwargs)
        for node in nodes:
            node.attrs.update(attrs_to_update)
        return soup

    def test_list_display(self, client, snapshot):
        membership = PrescriberMembershipFactory(
            organization__authorized=True, user__first_name="André", user__last_name="Dufour"
        )
        organization = membership.organization
        user = membership.user
        other_user = PrescriberFactory(
            first_name="Daphnée", last_name="Delavigne", membership__organization=organization
        )

        beneficiary = JobSeekerFactory(for_snapshot=True)
        other_beneficiary = JobSeekerFactory(first_name="Mary", last_name="Astell")

        client.force_login(user)
        response = client.get(self.LIST_URL)
        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot(name="empty page")

        with freeze_time(datetime.datetime(2026, 1, 15, 1, 0, tzinfo=datetime.UTC)):
            last_updated = OrientationFactory(
                id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
                beneficiary=beneficiary,
                sender=user,
                sender_prescriber_organization=organization,
                sender_kind=SenderKind.PRESCRIBER,
                service=ServiceFactory(name="S’hair-vice", structure__name="Structure à cuire"),
                created_at=datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.UTC),
            )
        with freeze_time(datetime.datetime(2026, 1, 15, 0, 0, tzinfo=datetime.UTC)):
            first_updated = OrientationFactory(
                id=uuid.UUID("00000000-1111-2222-3333-555555555555"),
                beneficiary=other_beneficiary,
                sender=other_user,
                sender_prescriber_organization=organization,
                sender_kind=SenderKind.PRESCRIBER,
                service=ServiceFactory(name="Sers vis", structure__name="Structure gonflable"),
                created_at=datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.UTC),
                status=OrientationStatus.REJECTED,
            )
        client.force_login(user)

        with assertSnapshotQueries(snapshot(name="queries")):
            response = client.get(self.LIST_URL)
        soup = parse_response_to_soup(response, selector="#main")
        for structure in [last_updated.service.structure, first_updated.service.structure]:
            soup = self.replace_attrs(
                soup,
                attrs={"name": "structures", "value": structure.pk},
                attrs_to_update={"value": "[PK of Structure]"},
            )
        for beneficiary in [last_updated.beneficiary, first_updated.beneficiary]:
            soup = self.replace_attrs(
                soup,
                attrs={"value": beneficiary.pk},
                attrs_to_update={"value": "[PK of Beneficiary]"},
                name="option",
            )
        for sender in [last_updated.sender, first_updated.sender]:
            soup = self.replace_attrs(
                soup,
                attrs={"value": sender.pk},
                attrs_to_update={"value": "[PK of Sender]"},
                name="option",
            )

        assert pretty_indented(soup) == snapshot(name="page")
        assert response.context["orientations_page"].object_list == [last_updated, first_updated]

    def test_non_authorized_prescriber_cannot_see_pii(self, client):
        membership = PrescriberMembershipFactory()
        user = membership.user
        organization = membership.organization

        beneficiary = JobSeekerFactory(
            first_name="Marimprobable",
            last_name="Astellrare",
        )

        OrientationFactory(
            beneficiary=beneficiary,
            sender=user,
            sender_prescriber_organization=organization,
            sender_kind=SenderKind.PRESCRIBER,
        )

        client.force_login(user)
        response = client.get(self.LIST_URL)

        assertNotContains(response, beneficiary.first_name)
        assertNotContains(response, beneficiary.last_name)
        assertContains(response, "A… M…", html=True)

    @override_settings(PAGE_SIZE_DEFAULT=1)
    def test_pagination(self, client):
        membership = PrescriberMembershipFactory(
            organization__authorized=True, user__first_name="André", user__last_name="Dufour"
        )
        organization = membership.organization
        user = membership.user
        OrientationFactory.create_batch(2, sender=user, sender_prescriber_organization=organization)
        client.force_login(user)
        response = client.get(self.LIST_URL)
        assertContains(response, PAGINATION_PAGE_ONE_MARKUP % (self.LIST_URL + "?page=1"), html=True)

    @pytest.mark.parametrize(
        "membership_factory",
        [CompanyMembershipFactory, partial(PrescriberMembershipFactory, organization__authorized=True)],
    )
    def test_list_contains_only_org_orientations(self, membership_factory, client):
        membership = membership_factory()
        user = membership.user

        prescriber_organization = None
        company = None
        other_prescriber_organization_same_user = None
        other_company_same_user = None
        other_prescriber_organization = None
        other_company = None
        if isinstance(membership, PrescriberMembership):
            sender_kind = SenderKind.PRESCRIBER
            prescriber_organization = membership.organization
            other_prescriber_organization_same_user = membership_factory(user=user).organization
            other_user_same_org = membership_factory(organization=prescriber_organization).user
            other_membership = PrescriberMembershipFactory()
            other_user = other_membership.user
            other_prescriber_organization = other_membership.organization
        elif isinstance(membership, CompanyMembership):
            sender_kind = SenderKind.EMPLOYER
            company = membership.company
            other_company_same_user = membership_factory(user=user).company
            other_user_same_org = membership_factory(company=company).user
            other_membership = CompanyMembershipFactory()
            other_user = other_membership.user
            other_company = other_membership.company

        # Orientation made by any user of current organization is displayed
        displayed_orientations = [
            OrientationFactory(
                sender_kind=sender_kind,
                sender=user,
                sender_prescriber_organization=prescriber_organization,
                sender_company=company,
            ),
            OrientationFactory(
                sender_kind=sender_kind,
                sender=other_user_same_org,
                sender_prescriber_organization=prescriber_organization,
                sender_company=company,
            ),
        ]

        # Other orientations are not displayed
        OrientationFactory(
            sender_kind=sender_kind,
            sender=user,
            sender_prescriber_organization=other_prescriber_organization_same_user,
            sender_company=other_company_same_user,
        )
        OrientationFactory(
            sender_kind=sender_kind,
            sender=other_user,
            sender_prescriber_organization=other_prescriber_organization,
            sender_company=other_company,
        )

        client.force_login(user)
        response = client.get(self.LIST_URL)
        assertQuerySetEqual(response.context["orientations_page"], displayed_orientations, ordered=False)

    def test_list_contains_all_statuses(self, client):
        membership = PrescriberMembershipFactory(organization__authorized=True)
        organization = membership.organization
        user = membership.user

        for status in OrientationStatus:
            OrientationFactory(sender=user, sender_prescriber_organization=organization, status=status)

        client.force_login(user)
        response = client.get(self.LIST_URL)
        displayed_statuses = [orientation.status for orientation in response.context["orientations_page"].object_list]
        assert set(displayed_statuses) == set(OrientationStatus.values)

    def test_no_results(self, client):
        client.force_login(PrescriberFactory(membership=True))

        response = client.get(self.LIST_URL)
        assertContains(response, "Aucune demande d’orientation pour le moment")

        response = client.get(self.LIST_URL, {"statuses": [OrientationStatus.PENDING]})
        assertContains(response, "Aucun résultat avec les filtres actuels")

    def test_htmx_filters(self, client):
        membership = PrescriberMembershipFactory(organization__authorized=True)
        organization = membership.organization
        user = membership.user
        status = random.choice(OrientationStatus.values)
        OrientationFactory(sender=user, sender_prescriber_organization=organization, status=status)
        client.force_login(user)

        response = client.get(self.LIST_URL)
        page = parse_response_to_soup(response, selector="#main")
        assertNotContains(response, self.RESET_BTN_MARKUP, html=True)

        # Simulate the data-emplois-sync-with and check both checkboxes.
        status_checkboxes = page.find_all("input", attrs={"name": "statuses", "value": status})
        assert len(status_checkboxes) == 2
        for status_checkbox in status_checkboxes:
            status_checkbox["checked"] = ""
        response = client.get(self.LIST_URL, {"statuses": [status]}, headers={"HX-Request": "true"})
        update_page_with_htmx(page, f"form[hx-get='{self.LIST_URL}']", response)

        response = client.get(self.LIST_URL, {"statuses": [status]})
        fresh_page = parse_response_to_soup(response, selector="#main")
        assertSoupEqual(page, fresh_page)

        assertContains(response, self.RESET_BTN_MARKUP, html=True)

    def test_beneficiary_filters(self, client):
        membership = PrescriberMembershipFactory(organization__authorized=True)
        organization = membership.organization
        user = membership.user
        orientation_jack = OrientationFactory(
            sender=user, sender_prescriber_organization=organization, beneficiary__first_name="Jack"
        )
        jack = orientation_jack.beneficiary
        orientation_mary = OrientationFactory(
            sender=user, sender_prescriber_organization=organization, beneficiary__first_name="Mary"
        )
        client.force_login(user)

        response = client.get(self.LIST_URL, {"beneficiary": jack.pk})
        assert response.context["orientations_page"].object_list == [orientation_jack]

        response = client.get(self.LIST_URL, {"beneficiary": ["INVALID"]})
        assert set(response.context["orientations_page"].object_list) == {orientation_jack, orientation_mary}
        assertContains(response, "Sélectionnez un choix valide. INVALID n’en fait pas partie.")

    def test_statuses_filters(self, client):
        membership = PrescriberMembershipFactory(organization__authorized=True)
        organization = membership.organization
        user = membership.user
        pending_orientation = OrientationFactory(
            sender=user, sender_prescriber_organization=organization, status=OrientationStatus.PENDING
        )
        rejected_orientation = OrientationFactory(
            sender=user, sender_prescriber_organization=organization, status=OrientationStatus.REJECTED
        )
        client.force_login(user)

        response = client.get(self.LIST_URL, {"statuses": [OrientationStatus.ACCEPTED.value]})
        assert response.context["orientations_page"].object_list == []

        response = client.get(self.LIST_URL, {"statuses": [OrientationStatus.PENDING.value]})
        assert response.context["orientations_page"].object_list == [pending_orientation]

        response = client.get(
            self.LIST_URL, {"statuses": [OrientationStatus.PENDING.value, OrientationStatus.REJECTED.value]}
        )
        assert set(response.context["orientations_page"].object_list) == {pending_orientation, rejected_orientation}

        response = client.get(self.LIST_URL, {"statuses": OrientationStatus.values})
        assert set(response.context["orientations_page"].object_list) == {pending_orientation, rejected_orientation}

        response = client.get(self.LIST_URL, {"statuses": ["INVALID"]})
        assert set(response.context["orientations_page"].object_list) == {pending_orientation, rejected_orientation}
        assertContains(response, "Sélectionnez un choix valide. INVALID n’en fait pas partie.")

        response = client.get(self.LIST_URL, {"statuses": ["INVALID"]})
        assert set(response.context["orientations_page"].object_list) == set(
            [pending_orientation, rejected_orientation]
        )
        assertContains(response, "Sélectionnez un choix valide. INVALID n’en fait pas partie.")

    def test_senders_filters_for_prescribers(self, client):
        membership = PrescriberMembershipFactory(organization__authorized=True)
        organization = membership.organization
        user = membership.user
        other_user = PrescriberMembershipFactory(organization=organization).user
        old_user = PrescriberMembershipFactory(organization=organization, is_active=False).user
        unrelated_user = OrientationFactory().sender
        orientation_1 = OrientationFactory(sender=user, sender_prescriber_organization=organization)
        orientation_2 = OrientationFactory(sender=other_user, sender_prescriber_organization=organization)
        orientation_3 = OrientationFactory(sender=old_user, sender_prescriber_organization=organization)
        client.force_login(user)

        response = client.get(self.LIST_URL, {"senders": [other_user.id]})
        assert response.context["orientations_page"].object_list == [orientation_2]

        response = client.get(self.LIST_URL, {"senders": [user.id, other_user.id, old_user.id]})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2, orientation_3}

        response = client.get(self.LIST_URL, {"senders": []})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2, orientation_3}

        response = client.get(self.LIST_URL, {"senders": [unrelated_user.pk]})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2, orientation_3}
        assertContains(response, f"Sélectionnez un choix valide. {unrelated_user.pk} n’en fait pas partie.")

    def test_senders_filters_for_employers(self, client):
        membership = CompanyMembershipFactory()
        company = membership.company
        user = membership.user
        other_user = CompanyMembershipFactory(company=company).user
        old_user = CompanyMembershipFactory(company=company, is_active=False).user
        unrelated_user = OrientationFactory().sender
        orientation_1 = OrientationFactory(
            sender=user,
            sender_prescriber_organization=None,
            sender_company=company,
            sender_kind=SenderKind.EMPLOYER,
        )
        orientation_2 = OrientationFactory(
            sender=other_user,
            sender_prescriber_organization=None,
            sender_company=company,
            sender_kind=SenderKind.EMPLOYER,
        )
        orientation_3 = OrientationFactory(
            sender=old_user,
            sender_prescriber_organization=None,
            sender_company=company,
            sender_kind=SenderKind.EMPLOYER,
        )
        client.force_login(user)

        response = client.get(self.LIST_URL, {"senders": [other_user.id]})
        assert response.context["orientations_page"].object_list == [orientation_2]

        response = client.get(self.LIST_URL, {"senders": [user.id, other_user.id, old_user.id]})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2, orientation_3}

        response = client.get(self.LIST_URL, {"senders": []})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2, orientation_3}

        response = client.get(self.LIST_URL, {"senders": [unrelated_user.pk]})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2, orientation_3}
        assertContains(response, f"Sélectionnez un choix valide. {unrelated_user.pk} n’en fait pas partie.")

    def test_structures_filters(self, client):
        membership = PrescriberMembershipFactory(organization__authorized=True)
        organization = membership.organization
        user = membership.user
        orientation_1 = OrientationFactory(sender=user, sender_prescriber_organization=organization)
        structure_1 = orientation_1.service.structure
        orientation_2 = OrientationFactory(sender=user, sender_prescriber_organization=organization)
        structure_2 = orientation_2.service.structure
        structure_3 = StructureFactory()
        client.force_login(user)

        response = client.get(self.LIST_URL, {"structures": [structure_1.id]})
        assert response.context["orientations_page"].object_list == [orientation_1]

        response = client.get(self.LIST_URL, {"structures": [structure_1.id, structure_2.id]})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2}

        response = client.get(self.LIST_URL, {"structures": []})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2}

        response = client.get(self.LIST_URL, {"structures": [structure_3.pk]})
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2}
        assertContains(response, f"Sélectionnez un choix valide. {structure_3.pk} n’en fait pas partie.")

    def test_mishmash_filters(self, client):
        membership = PrescriberMembershipFactory(organization__authorized=True)
        organization = membership.organization
        user = membership.user
        other_user = PrescriberMembershipFactory(organization=organization).user
        orientation_1 = OrientationFactory(
            sender=other_user, sender_prescriber_organization=organization, status=OrientationStatus.PENDING
        )
        orientation_2 = OrientationFactory(
            sender=user, sender_prescriber_organization=organization, status=OrientationStatus.REJECTED
        )
        client.force_login(user)

        response = client.get(
            self.LIST_URL,
            {
                "statuses": [OrientationStatus.PENDING.value],
                "structures": [orientation_1.service.structure.id],
                "beneficiary": orientation_1.beneficiary.pk,
                "senders": [other_user.pk],
            },
        )
        assert response.context["orientations_page"].object_list == [orientation_1]

        response = client.get(
            self.LIST_URL, {"statuses": ["INVALID"], "structures": [orientation_1.service.structure.id]}
        )
        assert set(response.context["orientations_page"].object_list) == {orientation_1, orientation_2}
        assertContains(response, "Sélectionnez un choix valide. INVALID n’en fait pas partie.")


class TestRegisterMobilizationEvent:
    @pytest.mark.parametrize("user_factory", [None, partial(PrescriberFactory, membership=True)])
    @pytest.mark.parametrize(
        "kind, with_service, service_external_link",
        [
            (MobilizationEventKind.STRUCTURE_CONTACT, False, ""),
            (MobilizationEventKind.SERVICE_CONTACT, True, ""),
            (MobilizationEventKind.SERVICE_EXT_LINK, True, "https://site.fake"),
        ],
    )
    def test_register_mobilization_event(self, client, user_factory, kind, with_service, service_external_link):
        structure = StructureFactory()
        service = ServiceFactory(structure=structure) if with_service else None

        if user_factory:
            user = user_factory()
            client.force_login(user)
        else:
            user = AnonymousUser()
            # Init session for anonymous user -- TODO: tweak client.force_login to allow force_login(AnonymousUser())
            client.get(reverse("insertion_views:structure_card", kwargs={"structure_uid": structure.uid}))

        data = {
            "kind": kind,
            "structure_uid": structure.uid,
            "service_uid": service.uid if with_service else "",
            "service_external_link": service_external_link,
        }
        response = client.post(reverse("insertion_views:register_mobilization_event"), data=data)
        assert response.content == b'{"message": "ok"}'

        assert MobilizationEvent.objects.filter(
            user=user if user_factory else None,
            kind=kind,
            structure=structure,
            service=service,
            service_external_link=service_external_link,
        ).exists()

    @pytest.mark.parametrize(
        "user_factory",
        [ItouStaffFactory, JobSeekerFactory, partial(LaborInspectorFactory, membership=True)],
    )
    def test_register_mobilization_event_bad_user(self, client, user_factory):
        structure = StructureFactory()
        user = user_factory()
        client.force_login(user)

        data = {"kind": MobilizationEventKind.STRUCTURE_CONTACT, "structure_uid": structure.uid, "service_uid": ""}
        response = client.post(reverse("insertion_views:register_mobilization_event"), data=data)

        assert response.status_code == 403
        assert not MobilizationEvent.objects.exists()

    @pytest.mark.parametrize(
        "kind,message,status_code,expected_exists",
        [
            (MobilizationEventKind.STRUCTURE_CONTACT.value, "", 200, True),
            ("", "missing or bad kind", 400, False),
            ("wrong_kind", "missing or bad kind", 400, False),
            (MobilizationEventKind.SERVICE_CONTACT.value, "", 500, False),
        ],
        ids=["good kind", "missing kind", "bad kind", "inconsistent kind (no service)"],
    )
    def test_register_mobilization_event_kind(self, client, kind, message, status_code, expected_exists):
        structure = StructureFactory()
        user = PrescriberFactory(membership=True)
        client.force_login(user)

        data = {"kind": kind, "structure_uid": structure.uid, "service_uid": ""}
        response = client.post(reverse("insertion_views:register_mobilization_event"), data=data)

        assert response.status_code == status_code
        if message:
            assert json.loads(response.content.decode()) == {"message": message}
        assert MobilizationEvent.objects.exists() is expected_exists

    @pytest.mark.parametrize(
        "structure_uid,service_uid,message,status_code,expected_exists",
        [
            # No service_uid
            ("structure-uid", "", "", 200, True),
            ("", "", "missing structure_uid", 400, False),
            ("inexisting-structure-uid", "", "", 404, False),
            # With service_uid
            ("structure-uid", "service-uid", "", 200, True),
            ("inexisting-structure-uid", "service-uid", "", 200, True),
            ("", "service-uid", "", 200, True),
            ("structure-uid", "inexisting-service-uid", "", 404, False),
        ],
    )
    def test_register_mobilization_event_structure_service(
        self, client, structure_uid, service_uid, message, status_code, expected_exists
    ):
        structure = StructureFactory(uid="structure-uid")
        ServiceFactory(uid="service-uid", structure=structure)
        user = PrescriberFactory(membership=True)
        client.force_login(user)

        kind = MobilizationEventKind.SERVICE_CONTACT if service_uid else MobilizationEventKind.STRUCTURE_CONTACT

        data = {"kind": kind, "structure_uid": structure_uid, "service_uid": service_uid}
        response = client.post(reverse("insertion_views:register_mobilization_event"), data=data)

        assert response.status_code == status_code
        if message:
            assert json.loads(response.content.decode()) == {"message": message}
        assert MobilizationEvent.objects.exists() is expected_exists
