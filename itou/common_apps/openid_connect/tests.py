import dataclasses
import datetime

from django.test import TestCase
from django.utils import timezone

from itou.inclusion_connect.models import InclusionConnectState, InclusionConnectUserData
from itou.users import enums as users_enums
from itou.users.factories import UserFactory
from itou.users.models import User

from .constants import OIDC_STATE_EXPIRATION


OIDC_USERINFO = {
    "given_name": "Michel",
    "family_name": "AUDIARD",
    "email": "michel@lestontons.fr",
    "sub": "af6b26f9-85cd-484e-beb9-bea5be13e30f",
}


class InclusionConnectModelTest(TestCase):
    # Test abstract class using one of its concrete implementation.
    def test_state_delete(self):
        state = InclusionConnectState.objects.create(csrf="foo")

        InclusionConnectState.objects.cleanup()

        state.refresh_from_db()
        self.assertIsNotNone(state)

        state.created_at = timezone.now() - OIDC_STATE_EXPIRATION * 2
        state.save()

        InclusionConnectState.objects.cleanup()

        with self.assertRaises(InclusionConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_create_user_from_user_info(self):
        """
        Nominal scenario: there is no user with the InclusionConnect ID or InclusionConnect email
        that is sent, so we create one.
        Similar to france_connect.tests.FranceConnectTest.test_create_django_user
        but with more tests.
        """
        ic_user_data = InclusionConnectUserData.from_user_info_dict(OIDC_USERINFO)
        self.assertFalse(User.objects.filter(username=ic_user_data.username).exists())
        self.assertFalse(User.objects.filter(email=ic_user_data.email).exists())

        user, created = ic_user_data.create_or_update_user()
        self.assertTrue(created)
        self.assertEqual(user.email, OIDC_USERINFO["email"])
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(user.username, OIDC_USERINFO["sub"])

        # TODO: this should be tested separately in User.test_models
        # TODO: update FC test to use PROVIDER_FRANCE_CONNECT instead.
        for field in dataclasses.fields(ic_user_data):
            self.assertEqual(
                user.external_data_source_history[field.name]["source"],
                users_enums.IdentityProvider.INCLUSION_CONNECT.name,
            )
            self.assertEqual(user.external_data_source_history[field.name]["value"], getattr(user, field.name))
            self.assertEqual(user.external_data_source_history[field.name]["created_at"].date(), datetime.date.today())

    def test_create_user_from_user_info_with_already_existing_id(self):
        """
        If there already is an existing user with this FranceConnectId, we do not create it again,
        we use it and we update it.
        """
        ic_user_data = InclusionConnectUserData.from_user_info_dict(OIDC_USERINFO)
        UserFactory(username=ic_user_data.username, last_name="will_be_forgotten")
        user, created = ic_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(
            user.external_data_source_history["last_name"]["source"],
            users_enums.IdentityProvider.INCLUSION_CONNECT.name,
        )

    def test_create_user_from_user_info_with_already_existing_email(self):
        """
        If there already is an existing user with email InclusionConnect sent us, we do not create it again,
        we use it but we do not update it.
        """
        ic_user_data = InclusionConnectUserData.from_user_info_dict(OIDC_USERINFO)
        UserFactory(email=ic_user_data.email)
        user, created = ic_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertNotEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertNotEqual(user.first_name, OIDC_USERINFO["given_name"])
        # We did not fill this data using external data, so it is not set.
        self.assertIsNone(user.external_data_source_history)

    def test_update_user_from_user_info(self):
        user = UserFactory(**dataclasses.asdict(InclusionConnectUserData.from_user_info_dict(OIDC_USERINFO)))
        ic_user = InclusionConnectUserData.from_user_info_dict(OIDC_USERINFO)

        # TODO: this should be tested separately.
        for field in dataclasses.fields(ic_user):
            value = getattr(ic_user, field.name)
            user.update_external_data_source_history_field(
                provider_name=users_enums.IdentityProvider.INCLUSION_CONNECT.name, field=field.name, value=value
            )
            user.save()

        new_ic_user = InclusionConnectUserData(
            first_name="Jean", last_name="Gabin", username=ic_user.username, email="jean@lestontons.fr"
        )
        user, created = new_ic_user.create_or_update_user()
        self.assertFalse(created)

        for field in dataclasses.fields(new_ic_user):
            value = getattr(new_ic_user, field.name)
            self.assertEqual(getattr(user, field.name), value)

        # TODO: this should be tested separately.
        # TODO: (celine-m-s) I'm not very comfortable with this behaviour as we don't really
        # keep a history of changes but only the last one.
        # Field name don't reflect actual behaviour.
        # Also, keeping a trace of old data is interesting in a debug purpose.
        for field in dataclasses.fields(new_ic_user):
            self.assertEqual(
                user.external_data_source_history[field.name]["source"],
                users_enums.IdentityProvider.INCLUSION_CONNECT.name,
            )
            self.assertEqual(user.external_data_source_history[field.name]["value"], getattr(user, field.name))
            # Because external_data_source_history is a JSONField,
            # dates are actually stored as strings in the database.
            created_at = user.external_data_source_history[field.name]["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.datetime.fromisoformat(created_at[:19])  # Remove milliseconds
            self.assertEqual(created_at.date(), datetime.date.today())
