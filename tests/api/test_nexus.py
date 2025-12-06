from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from itou.api.models import ServiceToken
from itou.nexus.enums import Role, Service
from itou.nexus.models import DEFAULT_THRESHOLD, APIFullSync, NexusMembership, NexusStructure, NexusUser
from tests.nexus.factories import NexusMembershipFactory, NexusStructureFactory, NexusUserFactory


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
        assert user.id == f"{source}--{user_data['id']}"
        assert user.source == source
        assert user.source_kind == user_data["kind"]
        for field in ["first_name", "last_name", "email", "phone", "auth"]:
            assert getattr(user, field) == user_data[field]
        assert user.last_login.isoformat() == user_data["last_login"]

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
                "memberships": [],
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 401

        response = api_client.delete(self.url, data={"id": "my-id"}, content_type="application/json")
        assert response.status_code == 401

    def test_create_user(self):
        api_client = self.api_client(service=Service.DORA)
        structure = NexusStructureFactory(source=Service.DORA)

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
                "memberships": [
                    {"structure_id": structure.source_id, "role": "ADMINISTRATOR"},
                ],
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202

        user = NexusUser.objects.get()
        self.assert_user_equals(user, Service.DORA, data[0])

        membership = NexusMembership.objects.get()
        assert membership.source == Service.DORA
        assert membership.structure == structure
        assert membership.user == user

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
                "memberships": [],
            }
        ]
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 0

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202
        updated_user = NexusUser.objects.get()
        assert updated_user.pk == user.pk
        self.assert_user_equals(updated_user, Service.DORA, data[0])
        assert NexusMembership.objects.count() == 0

    def test_update_user_add_membership(self):
        api_client = self.api_client(service=Service.DORA)
        structure = NexusStructureFactory(source=Service.DORA)

        user = NexusUserFactory(
            source=Service.DORA,
            kind="offreur",
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
                "memberships": [
                    {"structure_id": structure.source_id, "role": "ADMINISTRATOR"},
                ],
            }
        ]
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 0

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202
        updated_user = NexusUser.objects.get()
        assert updated_user.pk == user.pk
        self.assert_user_equals(updated_user, Service.DORA, data[0])

        membership = NexusMembership.objects.get()
        assert membership.source == Service.DORA
        assert membership.structure == structure
        assert membership.user == user

    def test_update_user_update_membership(self):
        api_client = self.api_client(service=Service.DORA)

        user = NexusUserFactory(
            source=Service.DORA,
            kind="offreur",
            first_name="A",
            last_name="B",
            email="old@mailinator.com",
            phone="0123456789",
            last_login=timezone.now().isoformat(),
            auth="PRO_CONNECT",
        )
        membership = NexusMembershipFactory(role=Role.ADMINISTRATOR, user=user, source=Service.DORA)
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
                "memberships": [
                    {"structure_id": membership.structure.source_id, "role": "COLLABORATOR"},
                ],
            }
        ]
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 1

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202
        updated_user = NexusUser.objects.get()
        assert updated_user.pk == user.pk
        self.assert_user_equals(updated_user, Service.DORA, data[0])

        updated_membership = NexusMembership.objects.get()
        assert updated_membership.source == Service.DORA
        assert updated_membership.structure == membership.structure
        assert updated_membership.user == user
        assert updated_membership.role == Role.COLLABORATOR

    def test_ignore_memberships_from_missing_structure(self):
        api_client = self.api_client(service=Service.DORA)

        data = [
            {
                "id": "my-id",
                "kind": "offreur",
                "first_name": "Jean",
                "last_name": "Bon",
                "email": "jean.bon@boucherie.fr",
                "phone": "",
                "last_login": timezone.now().isoformat(),
                "auth": "MAGIC_LINK",
                "memberships": [
                    {"structure_id": "3918bb96-9a69-428c-b01c-1cbea7141988", "role": "ADMINISTRATOR"},
                ],
            }
        ]

        # Silently ignore the membership if the structure does not exists
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 0

    def test_update_user_delete_old_memberships(self):
        api_client = self.api_client(service=Service.DORA)
        user = NexusUserFactory(source=Service.DORA, with_membership=True)
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 1
        assert NexusStructure.objects.count() == 1

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
                "memberships": [],
            }
        ]
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 1

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 0

    def test_create_and_update_multiple_users(self):
        api_client = self.api_client(service=Service.DORA)
        user = NexusUserFactory(source=Service.DORA)
        structure_1 = NexusStructureFactory(source=Service.DORA)
        structure_2 = NexusStructureFactory(source=Service.DORA)

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
                "memberships": [
                    {"structure_id": structure_1.source_id, "role": "ADMINISTRATOR"},
                    {"structure_id": structure_2.source_id, "role": "ADMINISTRATOR"},
                ],
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
                "memberships": [
                    {"structure_id": structure_1.source_id, "role": "COLLABORATOR"},
                ],
            },
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202
        assert NexusUser.objects.count() == 2
        assert NexusMembership.objects.count() == 3

    def test_delete_user(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        membership = NexusMembershipFactory(source=Service.COMMUNAUTE)
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 1
        assert NexusStructure.objects.count() == 1

        response = api_client.delete(self.url, data={"id": membership.user.source_id}, content_type="application/json")
        assert response.status_code == 202
        assert NexusUser.objects.count() == 0
        assert NexusMembership.objects.count() == 0  # Also removes the linked memberships
        assert NexusStructure.objects.count() == 1

    def test_delete_unknown_user(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        response = api_client.delete(self.url, data={"id": "my-id"}, content_type="application/json")
        assert response.status_code == 202

    def test_ignore_other_sources(self):
        api_client = self.api_client(service=Service.DORA)
        emplois_user = NexusUserFactory(source=Service.EMPLOIS)
        emplois_structure = NexusStructureFactory(source=Service.EMPLOIS)
        dora_structure = NexusStructureFactory(source=Service.DORA, source_id=emplois_structure.source_id)

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
                "memberships": [
                    {"structure_id": emplois_structure.source_id, "role": "ADMINISTRATOR"},
                ],
            },
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202

        assert NexusUser.objects.count() == 2
        dora_user = NexusUser.objects.exclude(pk=emplois_user.pk).get()
        assert dora_user.source_id == str(emplois_user.source_id)
        assert dora_user.source == Service.DORA

        dora_membership = NexusMembership.objects.get()
        assert dora_membership.source == Service.DORA
        assert dora_membership.user == dora_user
        assert dora_membership.structure == dora_structure

    def test_validate_payload(self):
        api_client = self.api_client(service=Service.DORA)
        structure = NexusStructureFactory(source=Service.DORA)

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
                "memberships": [
                    {
                        "structure_id": structure.source_id,
                        "role": "administrator",  # should be in upper case
                    },
                ],
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 400
        assert response.json() == [
            {
                "auth": ["«\xa0MAGIC LINK\xa0» n'est pas un choix valide."],
                "kind": ["employeur n'est pas un choix valide."],
                "memberships": [
                    {"role": ["«\xa0administrator\xa0» n'est pas un choix valide."]},
                ],
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
            }
        ]
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202

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
                "id": str(old_structure.source_id),
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
            }
        ]
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 202

        strucure = NexusStructure.objects.get()
        self.assert_structure_equals(strucure, Service.DORA, data[0])

    def test_delete_structure(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        membership = NexusMembershipFactory(source=Service.COMMUNAUTE)
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 1
        assert NexusStructure.objects.count() == 1

        response = api_client.delete(
            self.url, data={"id": membership.structure.source_id}, content_type="application/json"
        )
        assert response.status_code == 202
        assert NexusUser.objects.count() == 1
        assert NexusMembership.objects.count() == 0  # Also removes the linked memberships
        assert NexusStructure.objects.count() == 0

    def test_validate_payload(self, snapshot):
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
            }
        ]
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 400
        assert response.json() == [{"kind": ["«\xa0bad_kind\xa0» n'est pas un choix valide."]}]


class TestUpdateSyncedDateAPI(NexusApiTestMixin):
    url = reverse("v1:nexus-synced")

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

        response = api_client.post(self.url, data={"start": True, "started_at": timezone.now().isoformat()})
        assert response.status_code == 400

        assert APIFullSync.objects.exists() is False

    def test_api_post(self):
        assert APIFullSync.objects.exists() is False
        api_client = self.api_client(service=Service.DORA)

        with freeze_time() as frozen_time:
            response = api_client.post(self.url, data={"start": True}, content_type="application/json")
            assert response.status_code == 202
            assert response.json() == {"started_at": timezone.now().isoformat()}
            # NB: I used timezone.now() because frozen_time().isoformat() is missing the tz

            api_sync = APIFullSync.objects.get()
            assert api_sync.service == Service.DORA
            assert api_sync.timestamp == DEFAULT_THRESHOLD
            assert api_sync.new_start_at == timezone.now()

            frozen_time.tick()
            response = api_client.post(
                self.url, data={"started_at": response.json()["started_at"]}, content_type="application/json"
            )
            assert response.status_code == 202

            updated_api_synced = APIFullSync.objects.get()
            assert updated_api_synced.service == Service.DORA
            assert updated_api_synced.timestamp == api_sync.new_start_at
            assert updated_api_synced.new_start_at is None
