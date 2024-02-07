import pytest
from django.forms.models import model_to_dict

from itou.users.admin_forms import UserAdminForm
from itou.users.enums import IdentityProvider, UserKind
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


class UserAdminFormTest(TestCase):
    def test_kind(self):
        user = JobSeekerFactory()
        data_user = model_to_dict(user)
        data_user["kind"] = UserKind.ITOU_STAFF
        form = UserAdminForm(data=data_user, instance=user)
        assert not form.is_valid()
        with pytest.raises(ValueError):
            form.save()
        user.refresh_from_db()
        assert user.kind == UserKind.JOB_SEEKER

    def test_email_already_exists(self):
        # setup existing user
        email = "quention@django-unchained.com"
        JobSeekerFactory(email=email)

        # setup existing user for update tests
        user = JobSeekerFactory(email="christopher@nolan.com")
        data_user = model_to_dict(user)

        data_new_user = {
            "username": "johnwayne",
            "password": "foo",
            "email": "john@wayne.com",
            "kind": UserKind.JOB_SEEKER,
            "date_joined": "2022-02-02",
            "last_checked_at": "2022-02-02",
            "identity_provider": IdentityProvider.DJANGO,
        }

        # new user - email doesn't exist
        form = UserAdminForm(data_new_user)
        assert form.is_valid()

        # new user - email already exist
        data_new_user["email"] = user.email

        form = UserAdminForm(data_new_user)
        assert not form.is_valid()
        assert "Cet e-mail existe déjà." in form.errors["__all__"]

        # updating user - email not modified
        form = UserAdminForm(data=data_user, instance=user)
        assert form.is_valid()

        # updating user - email modified - email doesn't exist
        data_user["email"] = "ridley@scott.com"
        form = UserAdminForm(data=data_user, instance=user)
        assert form.is_valid()

        # updating user - email modified - email exist (other user)
        data_user["email"] = email
        form = UserAdminForm(data=data_user, instance=user)
        assert not form.is_valid()
        assert "Cet e-mail existe déjà." in form.errors["__all__"]
