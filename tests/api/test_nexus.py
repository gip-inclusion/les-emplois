from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from itou.api.models import ServiceToken
from itou.nexus.enums import Role, Service
from itou.nexus.models import Membership, Structure, User
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
                    {"structure_id": structure.source_id, "role": "administrator"},
                ],
            }
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201

        user = User.objects.get()
        self.assert_user_equals(user, Service.DORA, data[0])

        membership = Membership.objects.get()
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
        assert User.objects.count() == 1
        assert Membership.objects.count() == 0

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201
        updated_user = User.objects.get()
        assert updated_user.pk == user.pk
        self.assert_user_equals(updated_user, Service.DORA, data[0])
        assert Membership.objects.count() == 0

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
                    {"structure_id": structure.source_id, "role": "administrator"},
                ],
            }
        ]
        assert User.objects.count() == 1
        assert Membership.objects.count() == 0

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201
        updated_user = User.objects.get()
        assert updated_user.pk == user.pk
        self.assert_user_equals(updated_user, Service.DORA, data[0])

        membership = Membership.objects.get()
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
                    {"structure_id": membership.structure.source_id, "role": "collaborator"},
                ],
            }
        ]
        assert User.objects.count() == 1
        assert Membership.objects.count() == 1

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201
        updated_user = User.objects.get()
        assert updated_user.pk == user.pk
        self.assert_user_equals(updated_user, Service.DORA, data[0])

        updated_membership = Membership.objects.get()
        assert updated_membership.source == Service.DORA
        assert updated_membership.structure == membership.structure
        assert updated_membership.user == user
        assert updated_membership.role == "collaborator"

    def test_ignore_memberships_from_missing_structure(self):
        api_client = self.api_client(service=Service.DORA)

        data = [
            {
                "id": "my-id",
                "kind": "",
                "first_name": "Jean",
                "last_name": "Bon",
                "email": "jean.bon@boucherie.fr",
                "phone": "",
                "last_login": timezone.now().isoformat(),
                "auth": "MAGIC_LINK",
                "memberships": [
                    {"structure_id": "3918bb96-9a69-428c-b01c-1cbea7141988", "role": "administrator"},
                ],
            }
        ]

        # Silently ignore the membership if the structure does not exists
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201
        assert User.objects.count() == 1
        assert Membership.objects.count() == 0

    def test_update_user_delete_old_memberships(self):
        api_client = self.api_client(service=Service.DORA)
        user = NexusUserFactory(source=Service.DORA, with_membership=True)
        assert User.objects.count() == 1
        assert Membership.objects.count() == 1
        assert Structure.objects.count() == 1

        data = [
            {
                "id": user.source_id,
                "kind": user.source_kind,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "phone": user.phone,
                "last_login": user.last_login.isoformat(),
                "auth": user.auth,
                "memberships": [],
            }
        ]
        assert User.objects.count() == 1
        assert Membership.objects.count() == 1

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201
        assert User.objects.count() == 1
        assert Membership.objects.count() == 0

    def test_create_and_update_multiple_users(self):
        api_client = self.api_client(service=Service.DORA)
        user = NexusUserFactory(source=Service.DORA)
        structure_1 = NexusStructureFactory(source=Service.DORA)
        structure_2 = NexusStructureFactory(source=Service.DORA)

        data = [
            {
                "id": user.source_id,
                "kind": user.source_kind,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "phone": user.phone,
                "last_login": user.last_login.isoformat(),
                "auth": user.auth,
                "memberships": [
                    {"structure_id": structure_1.source_id, "role": "administrator"},
                    {"structure_id": structure_2.source_id, "role": "administrator"},
                ],
            },
            {
                "id": "my-id",
                "kind": "",
                "first_name": "Jean",
                "last_name": "Bon",
                "email": "jean.bon@boucherie.fr",
                "phone": "",
                "last_login": timezone.now().isoformat(),
                "auth": "MAGIC_LINK",
                "memberships": [
                    {"structure_id": structure_1.source_id, "role": "collaborator"},
                ],
            },
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201
        assert User.objects.count() == 2
        assert Membership.objects.count() == 3

    def test_delete_user(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        membership = NexusMembershipFactory(source=Service.COMMUNAUTE)
        assert User.objects.count() == 1
        assert Membership.objects.count() == 1
        assert Structure.objects.count() == 1

        response = api_client.delete(self.url, data={"id": membership.user.source_id}, content_type="application/json")
        assert response.status_code == 202
        assert User.objects.count() == 0
        assert Membership.objects.count() == 0  # Also removes the linked memberships
        assert Structure.objects.count() == 1

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
                "kind": emplois_user.source_kind,
                "first_name": emplois_user.first_name,
                "last_name": emplois_user.last_name,
                "email": emplois_user.email,
                "phone": emplois_user.phone,
                "last_login": emplois_user.last_login.isoformat(),
                "auth": emplois_user.auth,
                "memberships": [
                    {"structure_id": emplois_structure.source_id, "role": "administrator"},
                ],
            },
        ]

        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201

        assert User.objects.count() == 2
        dora_user = User.objects.exclude(pk=emplois_user.pk).get()
        assert dora_user.source_id == str(emplois_user.source_id)
        assert dora_user.source == Service.DORA

        dora_membership = Membership.objects.get()
        assert dora_membership.source == Service.DORA
        assert dora_membership.user == dora_user
        assert dora_membership.structure == dora_structure


class TestStructureAPI(NexusApiTestMixin):
    url = reverse("v1:nexus-structures")

    def assert_structure_equals(self, structure, source, structure_data):
        assert structure.id == f"{source}--{structure_data['id']}"
        assert structure.source == source
        assert structure.source_kind == structure_data["kind"]
        for field in ["name", "siret", "email", "phone"]:  # add address
            assert getattr(structure, field) == structure_data[field]

    def test_create_structure(self):
        api_client = self.api_client(service=Service.DORA)

        data = {
            "id": "my-id",
            "kind": "CCAS",
            "siret": "01234567891011",
            "name": "le CCAS du coin",
            "phone": "0123456789",
            "email": "ccas@malinator.com",
        }
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201

        strucure = Structure.objects.get()
        self.assert_structure_equals(strucure, Service.DORA, data)

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
        data = {
            "id": str(old_structure.source_id),
            "kind": "CCAS",
            "siret": "01234567891011",
            "name": "le CCAS du coin",
            "phone": "0123456789",
            "email": "ccas@malinator.com",
        }
        response = api_client.post(self.url, data=data, content_type="application/json")
        assert response.status_code == 201

        strucure = Structure.objects.get()
        self.assert_structure_equals(strucure, Service.DORA, data)

    def test_delete_structure(self):
        api_client = self.api_client(service=Service.COMMUNAUTE)
        membership = NexusMembershipFactory(source=Service.COMMUNAUTE)
        assert User.objects.count() == 1
        assert Membership.objects.count() == 1
        assert Structure.objects.count() == 1

        response = api_client.delete(
            self.url, data={"id": membership.structure.source_id}, content_type="application/json"
        )
        assert response.status_code == 202
        assert User.objects.count() == 1
        assert Membership.objects.count() == 0  # Also removes the linked memberships
        assert Structure.objects.count() == 0


# Test user kind mapping
# Test structure kind mapping
