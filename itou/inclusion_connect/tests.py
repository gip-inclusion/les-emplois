import dataclasses
import datetime

# import httpx
# import respx
from django.test import TestCase

# from django.urls import reverse
from django.utils import timezone

from ..users.factories import UserFactory
from ..users.models import User
from .constants import INCLUSION_CONNECT_STATE_EXPIRATION, PROVIDER_INCLUSION_CONNECT
from .models import InclusionConnectState, InclusionConnectUserData, create_or_update_user, userinfo_to_user_model_dict


INCLUSION_CONNECT_USERINFO = {
    "given_name": "Michel",
    "family_name": "AUDIARD",
    "email": "michel@lestontons.fr",
    "sub": "b6048e95bb134ec5b1d1e1fa69f287172e91722b9354d637a1bcf2ebb0fd2ef5v1",
}


class InclusionConnectModelTest(TestCase):
    # Same as france_connect.tests.FranceConnectTest.test_state_delete
    def test_state_delete(self):
        state = InclusionConnectState.objects.create(csrf="foo")

        InclusionConnectState.objects.cleanup()

        state.refresh_from_db()
        self.assertIsNotNone(state)

        # Set expired creation time for the state
        state.created_at = timezone.now() - INCLUSION_CONNECT_STATE_EXPIRATION * 2
        state.save()

        InclusionConnectState.objects.cleanup()

        with self.assertRaises(InclusionConnectState.DoesNotExist):
            state.refresh_from_db()

    def test_create_user_from_user_info(self):
        """
        Nominal scenario: there is no user with the InclusionConnect ID or InclusionConnect email
        that is sent, so we create one.
        Similar to france_connect.tests.FranceConnectTest.test_create_user_from_user_data
        but with more tests.
        """
        user_info = INCLUSION_CONNECT_USERINFO
        ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_info))
        self.assertFalse(User.objects.filter(username=ic_user_data.username).exists())
        self.assertFalse(User.objects.filter(email=ic_user_data.email).exists())

        user, created = create_or_update_user(ic_user_data)
        self.assertTrue(created)
        self.assertEqual(user.email, user_info["email"])
        self.assertEqual(user.last_name, user_info["family_name"])
        self.assertEqual(user.first_name, user_info["given_name"])
        self.assertEqual(user.username, user_info["sub"])

        # TODO: this should be tested separately in User.test_models
        # TODO: update FC test to use PROVIDER_FRANCE_CONNECT instead.
        for field in dataclasses.fields(ic_user_data):
            self.assertEqual(user.external_data_source_history[field.name]["source"], PROVIDER_INCLUSION_CONNECT)
            self.assertEqual(user.external_data_source_history[field.name]["value"], getattr(user, field.name))
            self.assertEqual(user.external_data_source_history[field.name]["created_at"].date(), datetime.date.today())

    def test_create_user_from_user_info_with_already_existing_ic_id(self):
        """
        If there already is an existing user with this FranceConnectId, we do not create it again,
        we use it and we update it.
        Similar to france_connect.tests.FranceConnectTest.test_create_user_*
        """
        user_info = INCLUSION_CONNECT_USERINFO
        ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_info))
        UserFactory(username=ic_user_data.username, last_name="will_be_forgotten")
        user, created = create_or_update_user(ic_user_data)
        self.assertFalse(created)
        self.assertEqual(user.last_name, user_info["family_name"])
        self.assertEqual(user.first_name, user_info["given_name"])
        self.assertEqual(user.external_data_source_history["last_name"]["source"], PROVIDER_INCLUSION_CONNECT)

    def test_create_user_from_user_info_with_already_existing_ic_email(self):
        """
        If there already is an existing user with email InclusionConnect sent us, we do not create it again,
        we use it but we do not update it.
        Similar to france_connect.tests.FranceConnectTest.test_create_user_*
        TODO: (celine-m-s) Check this behaviour.
        """
        user_info = INCLUSION_CONNECT_USERINFO
        ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_info))
        UserFactory(email=ic_user_data.email)
        user, created = create_or_update_user(ic_user_data)
        self.assertFalse(created)
        self.assertNotEqual(user.last_name, user_info["family_name"])
        self.assertNotEqual(user.first_name, user_info["given_name"])
        # We did not fill this data using external data, so it is not set.
        self.assertIsNone(user.external_data_source_history)

    def test_update_user_from_user_info(self):
        user_info = INCLUSION_CONNECT_USERINFO
        user = UserFactory(**userinfo_to_user_model_dict(user_info))
        ic_user_data = InclusionConnectUserData(**userinfo_to_user_model_dict(user_info))

        # TODO: this should be tested separately.
        for field in dataclasses.fields(ic_user_data):
            value = getattr(ic_user_data, field.name)
            user.update_external_data_source_history_field(
                provider_name=PROVIDER_INCLUSION_CONNECT, field=field.name, value=value
            )
            user.save()

        new_user_data = InclusionConnectUserData(
            first_name="Jean", last_name="Gabin", username=ic_user_data.username, email="jean@lestontons.fr"
        )
        user, created = create_or_update_user(new_user_data)
        self.assertFalse(created)

        for field in dataclasses.fields(new_user_data):
            value = getattr(new_user_data, field.name)
            self.assertEqual(getattr(user, field.name), value)

        # TODO: this should be tested separately.
        # TODO: (celine-m-s) I'm not very comfortable with this behaviour as we don't really
        # keep a history of changes but only the last one.
        # Field name don't reflect actual behaviour.
        # Also, keeping a trace of old data is interesting in a debug purpose.
        for field in dataclasses.fields(new_user_data):
            self.assertEqual(user.external_data_source_history[field.name]["source"], PROVIDER_INCLUSION_CONNECT)
            self.assertEqual(user.external_data_source_history[field.name]["value"], getattr(user, field.name))
            # Because external_data_source_history is a JSONField,
            # dates are actually stored as strings in the database.
            created_at = user.external_data_source_history[field.name]["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.datetime.fromisoformat(created_at[:19])  # Remove milliseconds
            self.assertEqual(created_at.date(), datetime.date.today())
