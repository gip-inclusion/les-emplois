from django.forms.models import model_to_dict
from django.test import TestCase

from itou.users.admin_forms import UserAdminForm
from itou.users.factories import JobSeekerFactory


class UserAdminFormTest(TestCase):

    # role counts

    # approval wrapper

    # email unicity
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
            "is_job_seeker": True,
            "date_joined": "2022-02-02",
        }

        # new user - email doesn't exist
        form = UserAdminForm(data_new_user)
        self.assertTrue(form.is_valid())

        # new user - email already exist
        data_new_user["email"] = user.email

        form = UserAdminForm(data_new_user)
        self.assertFalse(form.is_valid())
        self.assertIn("Cet e-mail existe déjà.", form.errors["__all__"])

        # updating user - email not modified
        form = UserAdminForm(data=data_user, instance=user)
        self.assertTrue(form.is_valid())

        # updating user - email modified - email doesn't exist
        data_user["email"] = "ridley@scott.com"
        form = UserAdminForm(data=data_user, instance=user)
        self.assertTrue(form.is_valid())

        # updating user - email modified - email exist (other user)
        data_user["email"] = email
        form = UserAdminForm(data=data_user, instance=user)
        self.assertFalse(form.is_valid())
        self.assertIn("Cet e-mail existe déjà.", form.errors["__all__"])
