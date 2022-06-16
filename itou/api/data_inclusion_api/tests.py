from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from itou.siaes.factories import SiaeConventionFactory, SiaeFactory
from itou.siaes.models import Siae
from itou.users.factories import SiaeStaffFactory


class DataInclusionStructureTest(APITestCase):
    url = reverse("v1:structures-list")
    maxDiff = None

    def setUp(self):
        self.user = SiaeStaffFactory()
        self.client = APIClient()
        self.authenticated_client = APIClient()
        self.authenticated_client.force_authenticate(self.user)

    def test_list_structures_unauthenticated(self):
        response = self.client.get(self.url, format="json")
        self.assertEqual(response.status_code, 403)

    def test_list_structures(self):
        def _str_with_tz(dt):
            return dt.astimezone(timezone.get_current_timezone()).isoformat()

        siae = SiaeFactory()
        antenne = SiaeFactory(source=Siae.SOURCE_USER_CREATED, convention=siae.convention)

        response = self.authenticated_client.get(self.url, format="json")
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
                },
            ],
        )

    def test_list_structures_description_longer_than_280(self):
        siae = SiaeFactory(description="a" * 300)

        response = self.authenticated_client.get(self.url, format="json")

        self.assertEqual(response.status_code, 200)
        siae_data = response.json()["results"][0]
        self.assertEqual(siae_data["presentation_resume"], siae.description[:279] + "…")
        self.assertEqual(siae_data["presentation_detail"], siae.description)

    def test_list_structures_inactive_excluded(self):
        convention = SiaeConventionFactory(is_active=False)
        SiaeFactory(convention=convention)

        response = self.authenticated_client.get(self.url, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
