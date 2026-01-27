import datetime

from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual
from rest_framework.test import APIClient

from itou.api.models import ServiceToken
from itou.nexus.enums import Service
from itou.nexus.models import DEFAULT_VALID_SINCE, NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.nexus.utils import service_id
from tests.nexus.factories import (
    NexusMembershipFactory,
    NexusRessourceSyncStatusFactory,
    NexusStructureFactory,
    NexusUserFactory,
)


class NexusApiTestMixin:
    def api_client(self, service=None):
        headers = {}
        if service is not None:
            token = ServiceToken.objects.create(service=service)
            headers = {"Authorization": f"Token {token.key}"}
        return APIClient(headers=headers)


class TestUserAPI(NexusApiTestMixin):
    url = reverse("v1:nexus-users")

    def assert_user_equals(self, user, source, user_data):
        assert user.pk == service_id(source, user_data["id"])
        assert user.source == source
        assert user.source_kind == user_data["kind"]
        for field in ["first_name", "last_name", "email", "phone", "auth"]:
            assert getattr(user, field) == user_data[field]
        if user.last_login is not None:
            assert user.last_login.isoformat() == user_data["last_login"]
        else:
            assert user_data["last_login"] is None

    def test_unauthenticated(self, api_client):
        api_client = self.api_client()

        data = [
            {
                "id": "my-id",
                "kind": "accompagnateur",
                "first_name": "Jean",
                "last_name": "Bon",
                "email": "jean.bon@boucherie.fr",
                "phone": "",
                "last_login": timezone.now().isoformat(),
                "auth": "MAGIC_LINK",
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 401

        response = api_client.delete(self.url, data={"id": "my-id"}, content_type="application/json")
        assert response.status_code == 401

    def test_create_user(self):
        api_client = self.api_client(service=Service.DORA)

        data = [
            {
                "id": "my-id",
                "kind": "accompagnateur",
                "first_name": "Jean",
                "last_name": "Bon",
                "email": "jean.bon@boucherie.fr",
                "phone": "",
                "last_login": None,
                "auth": "MAGIC_LINK",
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200

        user = NexusUser.objects.get()
        self.assert_user_equals(user, Service.DORA, data[0])

    def test_update_user(self):
        api_client = self.api_client(service=Service.DORA)

        user = NexusUserFactory(
            source=Service.DORA,
            kind="offreur",
            source_kind="offreur",
            first_name="A",
            last_name="B",
            email="old@mailinator.com",
            phone="0123456789",
            last_login=timezone.now().isoformat(),
            auth="PRO_CONNECT",
        )
        data = [
            {
                "id": user.source_id,
                "kind": "accompagnateur",
                "first_name": "Jean",
                "last_name": "Bon",
                "email": "jean.bon@boucherie.fr",
                "phone": "",
                "last_login": timezone.now().isoformat(),
                "auth": "MAGIC_LINK",
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200
        updated_user = NexusUser.objects.get()
        assert updated_user.pk == user.pk
        self.assert_user_equals(updated_user, Service.DORA, data[0])

    def test_create_and_update_multiple_users(self):
        api_client = self.api_client(service=Service.DORA)
        user = NexusUserFactory(source=Service.DORA)

        data = [
            {
                "id": user.source_id,
                "kind": "accompagnateur",
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "phone": user.phone,
                "last_login": user.last_login.isoformat(),
                "auth": user.auth,
            },
            {
                "id": "my-id",
                "kind": "offreur",
                "first_name": "Jean",
                "last_name": "Bon",
                "email": "jean.bon@boucherie.fr",
                "phone": "",
                "last_login": timezone.now().isoformat(),
                "auth": "MAGIC_LINK",
            },
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200
        assertQuerySetEqual(
            NexusUser.objects.all(),
            [
                (Service.DORA, user.pk),
                (Service.DORA, "dora--my-id"),
            ],
            ordered=False,
            transform=lambda user: (user.source, user.pk),
        )

    def test_delete_user(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        user_1 = NexusUserFactory(source=Service.COMMUNAUTE)
        user_2 = NexusMembershipFactory(source=Service.COMMUNAUTE).user

        response = api_client.delete(
            self.url,
            data=[{"id": user_1.source_id}, {"id": user_2.source_id}],
            content_type="application/json",
        )
        assert response.status_code == 200
        assert NexusUser.objects.count() == 0
        assert NexusMembership.objects.count() == 0  # Also removes the linked memberships (cascade)
        assert NexusStructure.objects.count() == 1

    def test_delete_unknown_user(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        response = api_client.delete(self.url, data=[{"id": "my-id"}], content_type="application/json")
        assert response.status_code == 404

    def test_ignore_other_sources(self):
        api_client = self.api_client(service=Service.DORA)
        emplois_user = NexusUserFactory(source=Service.EMPLOIS)

        data = [
            {
                "id": emplois_user.source_id,
                "kind": "accompagnateur_offreur",
                "first_name": emplois_user.first_name,
                "last_name": emplois_user.last_name,
                "email": emplois_user.email,
                "phone": emplois_user.phone,
                "last_login": emplois_user.last_login.isoformat(),
                "auth": emplois_user.auth,
            },
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200

        dora_user_id = f"dora--{emplois_user.source_id}"
        assertQuerySetEqual(
            NexusUser.objects.all(),
            [
                (Service.EMPLOIS, emplois_user.pk),
                (Service.DORA, dora_user_id),
            ],
            ordered=False,
            transform=lambda user: (user.source, user.pk),
        )

    def test_validate_payload(self):
        api_client = self.api_client(service=Service.DORA)

        data = [
            {
                "id": "my-id",
                "kind": "employeur",  # Not in dora kind mapping
                "first_name": "Jean",
                "last_name": "Bon",
                "email": "jean.bon@boucherie.fr",
                "phone": "",
                "last_login": timezone.now().isoformat(),
                "auth": "MAGIC LINK",  # missing underscore
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 400
        assert response.json() == [
            {
                "auth": ["«\xa0MAGIC LINK\xa0» n'est pas un choix valide."],
                "kind": ["«\xa0employeur\xa0» n'est pas un choix valide."],
            },
        ]


class TestStructureAPI(NexusApiTestMixin):
    url = reverse("v1:nexus-structures")

    def assert_structure_equals(self, structure, source, structure_data):
        assert structure.id == f"{source}--{structure_data['id']}"
        assert structure.source == source
        assert structure.source_kind == structure_data["kind"]
        for field in [
            "name",
            "siret",
            "email",
            "phone",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "department",
            "website",
            "opening_hours",
            "accessibility",
            "description",
            "source_link",
        ]:
            assert getattr(structure, field) == structure_data[field]

    def test_unauthenticated(self, api_client):
        api_client = self.api_client()

        data = [
            {
                "id": "my-id",
                "kind": "CCAS",
                "siret": "01234567891011",
                "name": "le CCAS du coin",
                "phone": "0123456789",
                "email": "ccas@malinator.com",
                "address_line_1": "26 rue de Berri",
                "address_line_2": "3e etage",
                "post_code": "75008",
                "city": "Paris",
                "department": "75",
                "accessibility": "",
                "description": "",
                "opening_hours": "",
                "source_link": "",
                "website": "",
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 401

        response = api_client.delete(self.url, data={"id": "my-id"}, content_type="application/json")
        assert response.status_code == 401

    def test_create_structure(self):
        api_client = self.api_client(service=Service.DORA)

        data = [
            {
                "id": "my-id",
                "kind": "CCAS",
                "siret": "01234567891011",
                "name": "le CCAS du coin",
                "phone": "0123456789",
                "email": "ccas@malinator.com",
                "address_line_1": "26 rue de Berri",
                "address_line_2": "3e etage",
                "post_code": "75008",
                "city": "Paris",
                "department": "75",
                "accessibility": "",
                "description": "",
                "opening_hours": "",
                "source_link": "",
                "website": "",
            }
        ]
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200

        strucure = NexusStructure.objects.get()
        self.assert_structure_equals(strucure, Service.DORA, data[0])

    def test_update_structure(self):
        api_client = self.api_client(service=Service.DORA)

        old_structure = NexusStructureFactory(
            source=Service.DORA,
            kind="EITI",
            siret="11109876543210",
            name="l'EITI d'ici",
            phone="0600000000",
            email="eiti@mailinator.com",
        )
        data = [
            {
                "id": old_structure.source_id,
                "kind": "CCAS",
                "siret": "01234567891011",
                "name": "le CCAS du coin",
                "phone": "0123456789",
                "email": "ccas@malinator.com",
                "address_line_1": "26 rue de Berri",
                "address_line_2": "3e etage",
                "post_code": "75008",
                "city": "Paris",
                "department": "75",
                "accessibility": "",
                "description": "",
                "opening_hours": "",
                "source_link": "",
                "website": "",
            }
        ]
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200

        strucure = NexusStructure.objects.get()
        self.assert_structure_equals(strucure, Service.DORA, data[0])

    def test_delete_structure(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        membership_1 = NexusMembershipFactory(source=Service.COMMUNAUTE)
        membership_2 = NexusMembershipFactory(source=Service.COMMUNAUTE)

        response = api_client.delete(
            self.url,
            data=[{"id": membership_1.structure.source_id}, {"id": membership_2.structure.source_id}],
            content_type="application/json",
        )
        assert response.status_code == 200
        assert NexusUser.objects.count() == 2
        assert NexusMembership.objects.count() == 0  # Also removes the linked memberships
        assert NexusStructure.objects.count() == 0

    def test_delete_unknown_structure(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)

        response = api_client.delete(self.url, data=[{"id": "my-id"}], content_type="application/json")
        assert response.status_code == 404

    def test_validate_payload(self):
        api_client = self.api_client(service=Service.DORA)

        data = [
            {
                "id": "my-id",
                "kind": "bad_kind",
                "siret": "01234567891011",
                "name": "le CCAS du coin",
                "phone": "0123456789",
                "email": "ccas@malinator.com",
                "address_line_1": "26 rue de Berri",
                "address_line_2": "3e etage",
                "post_code": "75008",
                "city": "Paris",
                "department": "75",
                "accessibility": "not an url",
                "description": "",
                "opening_hours": "",
                "source_link": "not an url",
                "website": "not an url",
            }
        ]
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 400
        assert response.json() == [
            {
                "kind": ["«\xa0bad_kind\xa0» n'est pas un choix valide."],
                "accessibility": ["Saisissez une URL valide."],
                "source_link": ["Saisissez une URL valide."],
                "website": ["Saisissez une URL valide."],
            },
        ]


class TestMembershipsAPI(NexusApiTestMixin):
    url = reverse("v1:nexus-memberships")

    def assert_membership_equals(self, membership, source, membership_data):
        assert membership.id == f"{source}--{membership_data['id']}"
        assert membership.source == source
        assert membership.user_id == f"{source}--{membership_data['user_id']}"
        assert membership.structure_id == f"{source}--{membership_data['structure_id']}"
        assert membership.role == membership_data["role"]

    def test_unauthenticated(self, api_client):
        api_client = self.api_client()
        user = NexusUserFactory(source=Service.DORA)
        structure = NexusStructureFactory(source=Service.DORA)

        data = [
            {
                "id": "my-id",
                "user_id": user.source_id,
                "structure_id": structure.source_id,
                "role": "ADMINISTRATOR",
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 401

        response = api_client.delete(self.url, data={"id": "my-id"}, content_type="application/json")
        assert response.status_code == 401

    def test_create_membership(self):
        api_client = self.api_client(service=Service.DORA)
        user = NexusUserFactory(source=Service.DORA)
        structure = NexusStructureFactory(source=Service.DORA)

        data = [
            {
                "id": "my-id",
                "user_id": user.source_id,
                "structure_id": structure.source_id,
                "role": "ADMINISTRATOR",
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200

        membership = NexusMembership.objects.get()
        self.assert_membership_equals(membership, Service.DORA, data[0])

    def test_update_membership(self):
        api_client = self.api_client(service=Service.DORA)
        membership = NexusMembershipFactory(source=Service.DORA)

        data = [
            {
                "id": membership.source_id,
                "user_id": membership.user.source_id,
                "structure_id": membership.structure.source_id,
                "role": "COLLABORATOR",
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200

        membership = NexusMembership.objects.get()
        self.assert_membership_equals(membership, Service.DORA, data[0])

    def test_ignore_memberships_from_missing_structure_or_user(self):
        api_client = self.api_client(service=Service.DORA)

        data = [
            {
                "id": "my-id",
                "user_id": "XXX",
                "structure_id": "YYY",
                "role": "ADMINISTRATOR",
            }
        ]

        # Silently ignore the membership if the structure or user dosen't exist
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 200
        assert NexusMembership.objects.count() == 0

    def test_delete_memberships(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        membership_1 = NexusMembershipFactory(source=Service.COMMUNAUTE)
        membership_2 = NexusMembershipFactory(source=Service.COMMUNAUTE)

        response = api_client.delete(
            self.url,
            data=[{"id": membership_1.source_id}, {"id": membership_2.source_id}],
            content_type="application/json",
        )
        assert response.status_code == 200
        assert NexusUser.objects.count() == 2
        assert NexusStructure.objects.count() == 2
        assert NexusMembership.objects.count() == 0

    def test_delete_unknown_structure(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)

        response = api_client.delete(self.url, data=[{"id": "my-di"}], content_type="application/json")
        assert response.status_code == 404

    def test_validate_payload(self):
        api_client = self.api_client(service=Service.DORA)
        user = NexusUserFactory(source=Service.DORA)
        structure = NexusStructureFactory(source=Service.DORA)

        data = [
            {
                "id": "my-id",
                "user_id": user.source_id,
                "structure_id": structure.source_id,
                "role": "administrator",  # should be in upper case
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 400
        assert response.json() == [
            {"role": ["«\xa0administrator\xa0» n'est pas un choix valide."]},
        ]


class TestSyncStartAPI(NexusApiTestMixin):
    url = reverse("v1:nexus-sync-start")

    def test_unauthenticated(self, api_client):
        api_client = self.api_client()

        response = api_client.post(self.url, content_type="application/json")
        assert response.status_code == 401

    def test_api_invalid_methods(self):
        api_client = self.api_client(service=Service.DORA)

        response = api_client.get(self.url, content_type="application/json")
        assert response.status_code == 405

        response = api_client.delete(self.url, content_type="application/json")
        assert response.status_code == 405

    def test_api_post(self):
        api_client = self.api_client(service=Service.DORA)

        with freeze_time() as frozen_time:
            response = api_client.post(self.url, content_type="application/json")
            assert response.status_code == 200
            assert response.json() == {"started_at": timezone.now().isoformat()}
            # NB: I used timezone.now() because frozen_time().isoformat() is missing the tz

            api_sync = NexusRessourceSyncStatus.objects.get()
            assert api_sync.service == Service.DORA
            assert api_sync.valid_since == DEFAULT_VALID_SINCE
            assert api_sync.in_progress_since == timezone.now()

            # Update existing NexusRessourceSyncStatus
            frozen_time.tick()
            response = api_client.post(self.url, content_type="application/json")
            assert response.status_code == 200
            assert response.json() == {"started_at": timezone.now().isoformat()}

            updated_api_sync = NexusRessourceSyncStatus.objects.get()
            assert updated_api_sync.service == Service.DORA
            assert updated_api_sync.valid_since == DEFAULT_VALID_SINCE
            assert updated_api_sync.in_progress_since == timezone.now()
            assert updated_api_sync.in_progress_since != api_sync.in_progress_since


class TestSyncCompletedAPI(NexusApiTestMixin):
    url = reverse("v1:nexus-sync-completed")

    def test_unauthenticated(self, api_client):
        api_client = self.api_client()

        response = api_client.post(self.url, content_type="application/json")
        assert response.status_code == 401

    def test_api_invalid_methods(self):
        api_client = self.api_client(service=Service.DORA)

        response = api_client.get(self.url, content_type="application/json")
        assert response.status_code == 405

        response = api_client.delete(self.url, content_type="application/json")
        assert response.status_code == 405

    def test_invalid_payloads(self):
        api_client = self.api_client(service=Service.DORA)

        # empty post
        response = api_client.post(self.url, content_type="application/json")
        assert response.status_code == 400
        assert response.json() == {"started_at": ["Ce champ est obligatoire."]}

        # service doesn't match
        start_at = timezone.now()
        NexusRessourceSyncStatusFactory(service=Service.EMPLOIS, in_progress_since=start_at)
        response = api_client.post(
            self.url, data={"started_at": start_at.isoformat()}, content_type="application/json"
        )
        assert response.status_code == 403

        # in_progress_since dosen't match
        NexusRessourceSyncStatusFactory(
            service=Service.DORA, in_progress_since=start_at + datetime.timedelta(seconds=1)
        )
        response = api_client.post(
            self.url, data={"started_at": start_at.isoformat()}, content_type="application/json"
        )
        assert response.status_code == 403

    def test_api_post(self):
        api_client = self.api_client(service=Service.DORA)

        start_at = timezone.now()
        NexusRessourceSyncStatusFactory(service=Service.DORA, in_progress_since=start_at)
        response = api_client.post(self.url, data={"started_at": start_at.isoformat()})
        assert response.status_code == 200

        updated_api_synced = NexusRessourceSyncStatus.objects.get()
        assert updated_api_synced.service == Service.DORA
        assert updated_api_synced.valid_since == start_at
        assert updated_api_synced.in_progress_since is None
