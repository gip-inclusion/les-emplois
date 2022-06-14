import dataclasses

from django.core.exceptions import ValidationError
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
        ic_user_data = InclusionConnectUserData.from_user_info(OIDC_USERINFO)
        self.assertFalse(User.objects.filter(username=ic_user_data.username).exists())
        self.assertFalse(User.objects.filter(email=ic_user_data.email).exists())

        user, created = ic_user_data.create_or_update_user()
        self.assertTrue(created)
        self.assertEqual(user.email, OIDC_USERINFO["email"])
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(user.username, OIDC_USERINFO["sub"])

        for field in dataclasses.fields(ic_user_data):
            with self.subTest(field):
                self.assertEqual(
                    user.external_data_source_history[field.name]["source"],
                    users_enums.IdentityProvider.INCLUSION_CONNECT.value,
                )
                self.assertEqual(user.external_data_source_history[field.name]["value"], getattr(user, field.name))

    def test_create_user_from_user_info_with_already_existing_id(self):
        """
        If there already is an existing user with this InclusionConnect id, we do not create it again,
        we use it and we update it.
        """
        ic_user_data = InclusionConnectUserData.from_user_info(OIDC_USERINFO)
        UserFactory(
            username=ic_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=users_enums.IdentityProvider.INCLUSION_CONNECT.value,
        )
        user, created = ic_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertEqual(user.first_name, OIDC_USERINFO["given_name"])
        self.assertEqual(
            user.external_data_source_history["last_name"]["source"],
            users_enums.IdentityProvider.INCLUSION_CONNECT.value,
        )

    def test_create_user_from_user_info_with_already_existing_id_but_from_other_sso(self):
        """
        If there already is an existing user with this InclusionConnect id, but it comes from another SSO.
        The email is also different, so it will crash while trying to create a new user.
        """
        ic_user_data = InclusionConnectUserData.from_user_info(OIDC_USERINFO)
        UserFactory(
            username=ic_user_data.username,
            last_name="will_be_forgotten",
            identity_provider=users_enums.IdentityProvider.DJANGO.value,
            email="random@email.com",
        )
        with self.assertRaises(ValidationError):
            ic_user_data.create_or_update_user()

    def test_create_user_from_user_info_with_already_existing_email(self):
        """
        If there already is an existing user with email InclusionConnect sent us, we do not create it again,
        we use it but we do not update it.
        """
        ic_user_data = InclusionConnectUserData.from_user_info(OIDC_USERINFO)
        UserFactory(email=ic_user_data.email)
        user, created = ic_user_data.create_or_update_user()
        self.assertFalse(created)
        self.assertNotEqual(user.last_name, OIDC_USERINFO["family_name"])
        self.assertNotEqual(user.first_name, OIDC_USERINFO["given_name"])
        # We did not fill this data using external data, so it is not set.
        self.assertFalse(user.external_data_source_history)

    def test_update_user_from_user_info(self):
        user = UserFactory(**dataclasses.asdict(InclusionConnectUserData.from_user_info(OIDC_USERINFO)))
        ic_user = InclusionConnectUserData.from_user_info(OIDC_USERINFO)

        new_ic_user = InclusionConnectUserData(
            first_name="Jean", last_name="Gabin", username=ic_user.username, email="jean@lestontons.fr"
        )
        user, created = new_ic_user.create_or_update_user()
        self.assertFalse(created)

        for field in dataclasses.fields(new_ic_user):
            with self.subTest(field):
                self.assertEqual(
                    user.external_data_source_history[field.name]["source"],
                    users_enums.IdentityProvider.INCLUSION_CONNECT.value,
                )
                self.assertEqual(getattr(user, field.name), getattr(new_ic_user, field.name))
