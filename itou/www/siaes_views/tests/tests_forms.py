from itou.cities.factories import create_city_guerande
from itou.jobs.factories import create_test_romes_and_appellations
from itou.siaes.enums import ContractType, SiaeKind
from itou.siaes.factories import SiaeFactory
from itou.utils.test import TestCase
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
            "job_appellation": "Whatever appellation",
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "Whatever contract type",
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

    def test_siae_errors(self):
        siae = SiaeFactory()
        post_data = {}

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        self.assertIsNotNone(form.errors)
        self.assertIn("job_appellation_code", form.errors.keys())
        self.assertIn("job_appellation", form.errors.keys())

        post_data.update(
            {
                "job_appellation_code": "10357",
                "job_appellation": "Whatever",
            }
        )

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        self.assertIsNotNone(form.errors)
        self.assertIn("contract_type", form.errors.keys())

        post_data.update(
            {
                "job_appellation_code": "10357",
                "job_appellation": "Whatever",
                "contract_type": ContractType.OTHER.value,
                "other_contract_type": "Whatever contract type",
                "open_positions": None,
            }
        )

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        self.assertIsNotNone(form.errors)
        self.assertIn("open_positions", form.errors.keys())

        post_data.update(
            {
                "open_positions": 3,
            }
        )

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        self.assertTrue(form.is_valid())

    def test_siae_fields(self):
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

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data

        self.assertEqual("description", cleaned_data.get("description"))
        self.assertEqual("profile_description", cleaned_data.get("profile_description"))

        # Checkboxes status
        self.assertTrue(cleaned_data.get("is_resume_mandatory"))

        del post_data["is_resume_mandatory"]

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data
        self.assertFalse(cleaned_data.get("is_resume_mandatory"))

    def test_opcs_errors(self):
        opcs = SiaeFactory(kind=SiaeKind.OPCS)
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
            "is_qpv_mandatory": "on",
        }

        form = EditJobDescriptionForm(current_siae=opcs, data=post_data)
        self.assertIsNotNone(form.errors)
        self.assertIn("market_context_description", form.errors.keys())

        post_data.update(
            {
                "market_context_description": "market_context_description",
            }
        )

        form = EditJobDescriptionForm(current_siae=opcs, data=post_data)
        self.assertTrue(form.is_valid())

    def test_opcs_fields(self):
        siae = SiaeFactory(kind=SiaeKind.OPCS)
        post_data = {
            "job_appellation_code": "10357",
            "job_appellation": "Whatever",
            "custom_name": "custom_name",
            "location_code": "guerande-44",
            "market_context_description": "market_context_description",
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": "on",
            "is_qpv_mandatory": "on",
        }

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data

        self.assertEqual("custom_name", cleaned_data.get("custom_name"))
        self.assertEqual("guerande-44", cleaned_data.get("location_code"))
        self.assertEqual(35, cleaned_data.get("hours_per_week"))
        self.assertEqual(5, cleaned_data.get("open_positions"))
        self.assertEqual("market_context_description", cleaned_data.get("market_context_description"))

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data

        self.assertEqual("description", cleaned_data.get("description"))
        self.assertEqual("profile_description", cleaned_data.get("profile_description"))

        # Checkboxes status
        self.assertTrue(cleaned_data.get("is_resume_mandatory"))
        self.assertTrue(cleaned_data.get("is_qpv_mandatory"))

        del post_data["is_resume_mandatory"]
        del post_data["is_qpv_mandatory"]

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data
        self.assertFalse(cleaned_data.get("is_resume_mandatory"))
        self.assertFalse(cleaned_data.get("is_qpv_mandatory"))


class EditJobDescriptionDetailsFormTest(TestCase):
    def test_siae_fields(self):
        siae = SiaeFactory()

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

        # Checkboxes status
        self.assertTrue(cleaned_data.get("is_resume_mandatory"))

        del post_data["is_resume_mandatory"]

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data
        self.assertFalse(cleaned_data.get("is_resume_mandatory"))

    def test_opcs_fields(self):
        siae = SiaeFactory(kind=SiaeKind.OPCS)

        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": "on",
            "is_qpv_mandatory": "on",
        }

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data

        self.assertEqual("description", cleaned_data.get("description"))
        self.assertEqual("profile_description", cleaned_data.get("profile_description"))

        # Checkboxes status
        self.assertTrue(cleaned_data.get("is_resume_mandatory"))
        self.assertTrue(cleaned_data.get("is_qpv_mandatory"))

        del post_data["is_resume_mandatory"]
        del post_data["is_qpv_mandatory"]

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        self.assertTrue(form.is_valid())

        cleaned_data = form.cleaned_data
        self.assertFalse(cleaned_data.get("is_resume_mandatory"))
        self.assertFalse(cleaned_data.get("is_qpv_mandatory"))
