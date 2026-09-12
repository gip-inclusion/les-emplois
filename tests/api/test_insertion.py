from django.urls import reverse
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from rest_framework.test import APIClient

from itou.api.models import DoraToken
from itou.insertion.enums import OrientationStatus
from itou.insertion.models import OrientationProcessLink
from itou.job_applications.enums import SenderKind
from tests.companies.factories import CompanyFactory
from tests.insertion.factories import OrientationFactory


class TestOrientationAPI:
    url = reverse("v1:orientations-list")

    def api_client(self):
        token = DoraToken.objects.create()
        headers = {"Authorization": f"Token {token.key}"}
        return APIClient(headers=headers)

    def test_unauthenticated(self, api_client):
        response = api_client.post(self.url)
        assert response.status_code == 401

        response = api_client.post(self.url, data={"structure_uid": "dora--structure-uid"})
        assert response.status_code == 401

    def test_list(self, snapshot):
        api_client = self.api_client()
        with freeze_time("2026-07-01"):
            accepted_orientation = OrientationFactory(
                status=OrientationStatus.ACCEPTED,
                beneficiary__first_name="Alix",
                beneficiary__last_name="Abé",
                beneficiary__jobseeker_profile__pole_emploi_id="1234567C",  # accepted orientation, will be displayed
                service__uid="service-uid-accepted-orientation",
                sender__first_name="Alexis",
                sender__last_name="Acé",
                sender_prescriber_organization__name="France Travail - Arles",
            )
        structure = accepted_orientation.service.structure

        with freeze_time("2026-08-01"):
            expired_orientation = OrientationFactory(
                status=OrientationStatus.EXPIRED,
                beneficiary__first_name="Bob",
                beneficiary__last_name="Bobard",
                beneficiary__jobseeker_profile__pole_emploi_id="hidden",  # will not be displayed
                service__uid="service-uid-expired-orientation",
                service__structure=structure,
                sender__first_name="Brice",
                sender__last_name="Bubble",
                sender_prescriber_organization__name="France Travail - Brest",
            )
        with freeze_time("2026-09-01"):
            refused_orientation = OrientationFactory(
                status=OrientationStatus.REJECTED,
                beneficiary__first_name="Charly",
                beneficiary__last_name="Cha",
                beneficiary__jobseeker_profile__pole_emploi_id="hidden",  # will not be displayed
                service__uid="service-uid-refused-orientation",
                service__structure=structure,
                sender__first_name="Chris",
                sender__last_name="Croutch",
                sender_prescriber_organization=None,
                sender_kind=SenderKind.EMPLOYER,
                sender_company=CompanyFactory(brand="Compas nie"),
                sender_company__brand="Compas nie",
            )

        # Orientation for another structure
        OrientationFactory(beneficiary__first_name="hidden", beneficiary__last_name="hidden")

        with assertSnapshotQueries(snapshot):
            response = api_client.post(self.url, data={"structure_uid": structure.uid})

        assert response.json()["results"] == [
            {
                "created_at": "2026-07-01T02:00:00+02:00",
                "status": "VALIDÉE",
                "beneficiary": "Alix ABÉ",
                "pole_emploi_id": "1234567C",
                "service": "service-uid-accepted-orientation",
                "sender_organization": "France Travail - Arles",
                "sender": "Alexis ACÉ",
                "process_link": accepted_orientation.process_links.first().process_link,
            },
            {
                "created_at": "2026-08-01T02:00:00+02:00",
                "status": "EXPIRÉE",
                "beneficiary": "Bob BOBARD",
                "pole_emploi_id": None,
                "service": "service-uid-expired-orientation",
                "sender_organization": "France Travail - Brest",
                "sender": "Brice BUBBLE",
                "process_link": expired_orientation.process_links.first().process_link,
            },
            {
                "created_at": "2026-09-01T02:00:00+02:00",
                "status": "REFUSÉE",
                "beneficiary": "Charly CHA",
                "pole_emploi_id": None,
                "service": "service-uid-refused-orientation",
                "sender_organization": "Compas nie",
                "sender": "Chris CROUTCH",
                "process_link": refused_orientation.process_links.first().process_link,
            },
        ]

    def test_generate_process_link_only_for_current_page(self, settings):
        api_client = self.api_client()
        structure = OrientationFactory().service.structure
        OrientationFactory(service__structure=structure)
        assert not OrientationProcessLink.objects.exists()

        response = api_client.post(self.url + "?page_size=1", data={"structure_uid": structure.uid})
        assert response.json()["next"] is not None
        assert OrientationProcessLink.objects.count() == 1
