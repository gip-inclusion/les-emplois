from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from itou.prescribers.factories import PrescriberOrganizationFactory
from itou.siaes.factories import SiaeConventionFactory, SiaeFactory
from itou.siaes.models import Siae
from itou.users.factories import PrescriberFactory, SiaeStaffFactory


def _str_with_tz(dt):
    return dt.astimezone(timezone.get_current_timezone()).isoformat()


class DataInclusionStructureTest(APITestCase):
    maxDiff = None

    def test_list_missing_type_query_param(self):
        user = SiaeStaffFactory()
        authenticated_client = APIClient()
        authenticated_client.force_authenticate(user)
        url = reverse("v1:structures-list")

        response = authenticated_client.get(url, format="json")
        self.assertEqual(response.status_code, 400)


class DataInclusionSiaeStructureTest(APITestCase):
    url = reverse("v1:structures-list")
    maxDiff = None

    def setUp(self):
        self.user = SiaeStaffFactory()
        self.client = APIClient()
        self.authenticated_client = APIClient()
        self.authenticated_client.force_authenticate(self.user)

    def test_list_structures_unauthenticated(self):
        response = self.client.get(self.url, format="json", data={"type": "siae"})
        self.assertEqual(response.status_code, 401)

    def test_list_structures(self):
        siae = SiaeFactory()
        antenne = SiaeFactory(source=Siae.SOURCE_USER_CREATED, convention=siae.convention)

        response = self.authenticated_client.get(
            self.url,
            format="json",
            data={"type": "siae"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "id": str(siae.uid),
                    "typologie": siae.kind.value,
                    "nom": siae.display_name,
                    "siret": siae.siret,
                    "rna": "",
                    "presentation_resume": "",
                    "presentation_detail": "",
                    "site_web": siae.website,
                    "telephone": siae.phone,
                    "courriel": siae.email,
                    "code_postal": siae.post_code,
                    "code_insee": "",
                    "commune": siae.city,
                    "adresse": siae.address_line_1,
                    "complement_adresse": siae.address_line_2,
                    "longitude": siae.longitude,
                    "latitude": siae.latitude,
                    "source": siae.source,
                    "date_maj": _str_with_tz(siae.updated_at),
                    "structure_parente": None,
                    "lien_source": f"http://testserver{reverse('siaes_views:card', kwargs={'siae_id': siae.pk})}",
                },
                {
                    "id": str(antenne.uid),
                    "typologie": antenne.kind.value,
                    "nom": antenne.display_name,
                    "siret": antenne.siret,
                    "rna": "",
                    "presentation_resume": "",
                    "presentation_detail": "",
                    "site_web": antenne.website,
                    "telephone": antenne.phone,
                    "courriel": antenne.email,
                    "code_postal": antenne.post_code,
                    "code_insee": "",
                    "commune": antenne.city,
                    "adresse": antenne.address_line_1,
                    "complement_adresse": antenne.address_line_2,
                    "longitude": antenne.longitude,
                    "latitude": antenne.latitude,
                    "source": antenne.source,
                    "date_maj": _str_with_tz(antenne.updated_at),
                    # Antenne references parent structure
                    "structure_parente": str(siae.uid),
                    "lien_source": f"http://testserver{reverse('siaes_views:card', kwargs={'siae_id': antenne.pk})}",
                },
            ],
        )

    def test_list_structures_description_longer_than_280(self):
        siae = SiaeFactory(description="a" * 300)

        response = self.authenticated_client.get(
            self.url,
            format="json",
            data={"type": "siae"},
        )

        self.assertEqual(response.status_code, 200)
        structure_data = response.json()["results"][0]
        self.assertEqual(structure_data["presentation_resume"], siae.description[:279] + "…")
        self.assertEqual(structure_data["presentation_detail"], siae.description)

    def test_list_structures_inactive_excluded(self):
        convention = SiaeConventionFactory(is_active=False)
        SiaeFactory(convention=convention)

        response = self.authenticated_client.get(
            self.url,
            format="json",
            data={"type": "siae"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])


class DataInclusionPrescriberStructureTest(APITestCase):
    url = reverse("v1:structures-list")
    maxDiff = None

    def setUp(self):
        self.user = PrescriberFactory()
        self.client = APIClient()
        self.authenticated_client = APIClient()
        self.authenticated_client.force_authenticate(self.user)

    def test_list_structures_unauthenticated(self):
        response = self.client.get(self.url, format="json", data={"type": "orga"})
        self.assertEqual(response.status_code, 401)

    def test_list_structures(self):
        orga = PrescriberOrganizationFactory(is_authorized=True)

        response = self.authenticated_client.get(
            self.url,
            format="json",
            data={"type": "orga"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "id": str(orga.uid),
                    "typologie": orga.kind.value,
                    "nom": orga.name,
                    "siret": orga.siret,
                    "rna": "",
                    "presentation_resume": "",
                    "presentation_detail": "",
                    "site_web": orga.website,
                    "telephone": orga.phone,
                    "courriel": orga.email,
                    "code_postal": orga.post_code,
                    "code_insee": "",
                    "commune": orga.city,
                    "adresse": orga.address_line_1,
                    "complement_adresse": orga.address_line_2,
                    "longitude": orga.longitude,
                    "latitude": orga.latitude,
                    "source": "",
                    "date_maj": _str_with_tz(orga.created_at),
                    "structure_parente": None,
                    "lien_source": f"http://testserver{reverse('prescribers_views:card', kwargs={'org_id': orga.pk})}",
                }
            ],
        )

    def test_list_structures_date_maj_value(self):
        orga = PrescriberOrganizationFactory()

        response = self.authenticated_client.get(
            self.url,
            format="json",
            data={"type": "orga"},
        )

        self.assertEqual(response.status_code, 200)
        structure_data = response.json()["results"][0]
        self.assertEqual(structure_data["date_maj"], _str_with_tz(orga.created_at))

        orga.description = "lorem ipsum"
        orga.save()

        response = self.authenticated_client.get(
            self.url,
            format="json",
            data={"type": "orga"},
        )
        self.assertEqual(response.status_code, 200)
        structure_data = response.json()["results"][0]
        self.assertEqual(structure_data["date_maj"], _str_with_tz(orga.updated_at))

    def test_list_structures_description_longer_than_280(self):
        orga = PrescriberOrganizationFactory(description="a" * 300)

        response = self.authenticated_client.get(
            self.url,
            format="json",
            data={"type": "orga"},
        )

        self.assertEqual(response.status_code, 200)
        structure_data = response.json()["results"][0]
        self.assertEqual(structure_data["presentation_resume"], orga.description[:279] + "…")
        self.assertEqual(structure_data["presentation_detail"], orga.description)
