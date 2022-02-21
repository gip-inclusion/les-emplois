from django.test import TestCase

from itou.cities.factories import create_city_guerande
from itou.jobs.factories import create_test_romes_and_appellations
from itou.siaes.factories import SiaeFactory
from itou.siaes.models import ContractType
from itou.www.siaes_views.forms import EditJobDescriptionDetailsForm, EditJobDescriptionForm


class EditSiaeJobDescriptionFormTest(TestCase):
    def setUp(self):
        super().setUp()
        # Needed to create sample ROME codes and job appellations (no fixture for ROME codes)
        create_test_romes_and_appellations(["M1805", "N1101"], appellations_per_rome=2)
        # Same for location field
        create_city_guerande()

    def test_clean_contract_type(self):
        siae = SiaeFactory()
        post_data = {
            "job_appellation_code": "10357",
            "job_appellation": "Whatever",  # job_appellation_code prevails
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": None,
            "open_positions": "1",
        }

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)

        self.assertIsNotNone(form.errors.get("other_contract_type"))

        post_data["other_contract_type"] = "CDD new generation"
        form = EditJobDescriptionForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

    def test_clean_open_positions(self):
        siae = SiaeFactory()
        post_data = {
            "job_appellation_code": "10357",
            "job_appellation": "Whatever",
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "Whatever",
            "open_positions": None,
        }

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        self.assertIsNotNone(form.errors.get("open_positions"))

        post_data["open_positions"] = "0"
        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        self.assertIsNotNone(form.errors.get("open_positions"))

        post_data["open_positions"] = "1"
        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        self.assertTrue(form.is_valid())

    def test_non_required_fields(self):
        siae = SiaeFactory()
        post_data = {
            "job_appellation_code": "10357",
            "job_appellation": "Whatever",
            "custom_name": "custom_name",
            "location_code": "guerande-44",
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": "on",
        }

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data

        self.assertEqual("custom_name", cleaned_data.get("custom_name"))
        self.assertEqual("guerande-44", cleaned_data.get("location_code"))
        self.assertEqual(35, cleaned_data.get("hours_per_week"))
        self.assertEqual(5, cleaned_data.get("open_positions"))


class EditJobDescriptionDetailsFormTest(TestCase):
    def test_non_required_fields(self):
        siae = SiaeFactory()

        post_data = {
            "description": "description",
            "profile_description": "profile_description",
        }
        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": "on",
        }

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data

        self.assertEqual("description", cleaned_data.get("description"))
        self.assertEqual("profile_description", cleaned_data.get("profile_description"))
        self.assertEqual(True, cleaned_data.get("is_resume_mandatory"))
