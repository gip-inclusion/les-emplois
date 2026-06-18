from unittest.mock import patch

import pytest
from django.conf import settings
from django.urls import reverse
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateUsed

from itou.insertion.models import SOURCE_DORA_VALUE, GenericReferenceItemKind, GenericReferenceItemSource
from tests.insertion.factories import GenericReferenceItemFactory, ServiceFactory, StructureFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import PrescriberFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


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
        )
        response = client.get(self.get_structure_url(structure))

        modal = parse_response_to_soup(response, selector="#structure-contact-modal")
        assert pretty_indented(modal) == snapshot


class TestServices:
    LOGIN_URL = reverse("login:existing_user")
    ORIENT_BTN_LABEL = "Orienter le bénéficiaire"
    DISPLAY_SERVICE_CONTACT_BTN = 'data-bs-target="#service-contact-modal"'
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
            uid="test-orientable-uid",
            name="Service orientable",
            updated_on="2025-01-15",
            is_orientable_with_form=False,
            mobilization_modes_professionals_external_form_link="https://test.example.com",
            structure__uid="test-structure-orientable-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertContains(response, self.ORIENT_BTN_LABEL)
        assertContains(response, f'href="{test_link}"')
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

    def test_detail_contact_section_hidden_without_contact_info(self, client):
        user = PrescriberFactory(membership=True)
        service = ServiceFactory(
            uid="test-no-contact-uid",
            updated_on="2025-01-15",
            contact_full_name="",
            contact_email="",
            contact_phone="",
            structure__uid="test-structure-no-contact-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(user)
        response = client.get(self.get_service_url(service))
        assertNotContains(response, "Voir les coordonnées de contact du service")

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
        assertContains(response, self.DISPLAY_SERVICE_CONTACT_BTN)

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
        assertContains(response, self.DISPLAY_SERVICE_CONTACT_BTN)

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
        assertNotContains(response, self.DISPLAY_SERVICE_CONTACT_BTN)

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

    @pytest.mark.parametrize("is_authorized", [True, False])
    def test_detail_orientation_url_with_jwt_for_prescriber(self, client, is_authorized):
        organization = PrescriberOrganizationFactory(authorized=is_authorized)
        prescriber = PrescriberFactory(membership=True, membership__organization=organization)
        service = ServiceFactory(
            uid="test-jwt-uid",
            updated_on="2025-01-15",
            is_orientable_with_form=True,
            structure__uid="test-structure-jwt-uid",
            structure__updated_on="2025-01-15",
        )
        client.force_login(prescriber)

        orientation_token = "jwt-token"

        with patch("itou.www.insertion_views.views.get_orientation_jwt", return_value=orientation_token):
            response = client.get(self.get_service_url(service))

        assert response.status_code == 200

        # Regular prescribers get direct DORA URL without nexus auto_login
        regular_dora_url = (
            f"https://dora.inclusion.gouv.fr/services/di--{service.uid}/orienter"
            f"?mtm_campaign=lesemplois&amp;mtm_kwd=service-professional"
        )
        # Authorized ProConnect prescribers get orientation URL wrapped in nexus auto_login with JWT
        authorized_dora_url = reverse(
            "nexus:auto_login",
            query={
                "next_url": f"https://dora.inclusion.gouv.fr/services/di--{service.uid}/orienter"
                f"?mtm_campaign=lesemplois&mtm_kwd=service-professional&op={orientation_token}"
            },
        )

        if is_authorized:
            assertContains(response, authorized_dora_url)
        else:
            assertNotContains(response, authorized_dora_url)
            assertContains(response, regular_dora_url)
            assertNotContains(response, "op=")

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
