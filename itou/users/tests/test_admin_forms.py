from django.forms.models import model_to_dict
from django.test import TestCase

from itou.approvals.factories import ApprovalFactory
from itou.users.admin_forms import UserAdminForm
from itou.users.enums import IdentityProvider
from itou.users.factories import JobSeekerFactory


class UserAdminFormTest(TestCase):
    def test_role_counts(self):
        user = JobSeekerFactory()
        data_user = model_to_dict(user)
        data_user["is_job_seeker"] = True
        data_user["is_prescriber"] = True
        form = UserAdminForm(data=data_user, instance=user)
        self.assertFalse(form.is_valid())
        self.assertIn("Un utilisateur ne peut avoir qu'un rôle à la fois", form.errors["__all__"][0])

    def test_pass_iae_and_job_seeker(self):
        user = JobSeekerFactory()
        ApprovalFactory(user=user)
        data_user = model_to_dict(user)
        data_user["is_job_seeker"] = False
        data_user["is_prescriber"] = True
        data_user["is_siae_staff"] = False
        data_user["is_labor_inspector"] = False
        form = UserAdminForm(data=data_user, instance=user)
        self.assertFalse(form.is_valid())
        self.assertIn("Cet utilisateur possède déjà un PASS IAE", form.errors["__all__"][0])

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
            "identity_provider": IdentityProvider.DJANGO,
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
