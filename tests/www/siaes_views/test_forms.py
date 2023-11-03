from itou.companies.enums import CompanyKind, ContractType
from itou.www.companies_views.forms import EditJobDescriptionDetailsForm, EditJobDescriptionForm
from tests.cities.factories import create_city_guerande
from tests.companies.factories import SiaeFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.utils.test import TestCase


class EditSiaeJobDescriptionFormTest(TestCase):
    def setUp(self):
        super().setUp()
        # Needed to create sample ROME codes and job appellations (no fixture for ROME codes)
        create_test_romes_and_appellations(["M1805", "N1101"], appellations_per_rome=2)
        # Same for location field
        self.guerande_city = create_city_guerande()

    def test_clean_contract_type(self):
        siae = SiaeFactory()
        post_data = {
            "appellation": "10357",
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": None,
            "open_positions": "1",
        }

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)

        assert form.errors.get("other_contract_type") is not None

        post_data["other_contract_type"] = "CDD new generation"
        form = EditJobDescriptionForm(current_siae=siae, data=post_data)

        assert form.is_valid()

    def test_clean_open_positions(self):
        siae = SiaeFactory()
        post_data = {
            "appellation": "10357",
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "Whatever contract type",
            "open_positions": None,
        }

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        assert form.errors.get("open_positions") is not None

        post_data["open_positions"] = "0"
        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        assert form.errors.get("open_positions") is not None

        post_data["open_positions"] = "1"
        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        assert form.is_valid()

    def test_siae_errors(self):
        siae = SiaeFactory()
        post_data = {}

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        assert form.errors is not None
        assert "appellation" in form.errors.keys()

        post_data.update(
            {
                "appellation": "10357",
            }
        )

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        assert form.errors is not None
        assert "contract_type" in form.errors.keys()

        post_data.update(
            {
                "appellation": "10357",
                "contract_type": ContractType.OTHER.value,
                "other_contract_type": "Whatever contract type",
                "open_positions": None,
            }
        )

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        assert form.errors is not None
        assert "open_positions" in form.errors.keys()

        post_data.update(
            {
                "open_positions": 3,
            }
        )

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)
        assert form.is_valid()

    def test_siae_fields(self):
        siae = SiaeFactory()
        post_data = {
            "appellation": "10357",
            "custom_name": "custom_name",
            "location": self.guerande_city.pk,
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": "on",
        }

        form = EditJobDescriptionForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data

        assert "custom_name" == cleaned_data.get("custom_name")
        assert self.guerande_city == cleaned_data.get("location")
        assert 35 == cleaned_data.get("hours_per_week")
        assert 5 == cleaned_data.get("open_positions")

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data

        assert "description" == cleaned_data.get("description")
        assert "profile_description" == cleaned_data.get("profile_description")

        # Checkboxes status
        assert cleaned_data.get("is_resume_mandatory")

        del post_data["is_resume_mandatory"]

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data
        assert not cleaned_data.get("is_resume_mandatory")

    def test_opcs_errors(self):
        opcs = SiaeFactory(kind=CompanyKind.OPCS)
        post_data = {
            "appellation": "10357",
            "custom_name": "custom_name",
            "location": self.guerande_city.pk,
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
        assert form.errors is not None
        assert "market_context_description" in form.errors.keys()

        post_data.update(
            {
                "market_context_description": "market_context_description",
            }
        )

        form = EditJobDescriptionForm(current_siae=opcs, data=post_data)
        assert form.is_valid()

    def test_opcs_fields(self):
        siae = SiaeFactory(kind=CompanyKind.OPCS)
        post_data = {
            "appellation": "10357",
            "custom_name": "custom_name",
            "location": self.guerande_city.pk,
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

        assert form.is_valid()

        cleaned_data = form.cleaned_data

        assert "custom_name" == cleaned_data.get("custom_name")
        assert self.guerande_city == cleaned_data.get("location")
        assert 35 == cleaned_data.get("hours_per_week")
        assert 5 == cleaned_data.get("open_positions")
        assert "market_context_description" == cleaned_data.get("market_context_description")

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data

        assert "description" == cleaned_data.get("description")
        assert "profile_description" == cleaned_data.get("profile_description")

        # Checkboxes status
        assert cleaned_data.get("is_resume_mandatory")
        assert cleaned_data.get("is_qpv_mandatory")

        del post_data["is_resume_mandatory"]
        del post_data["is_qpv_mandatory"]

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data
        assert not cleaned_data.get("is_resume_mandatory")
        assert not cleaned_data.get("is_qpv_mandatory")


class EditJobDescriptionDetailsFormTest(TestCase):
    def test_siae_fields(self):
        siae = SiaeFactory()

        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": "on",
        }

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data

        assert "description" == cleaned_data.get("description")
        assert "profile_description" == cleaned_data.get("profile_description")

        # Checkboxes status
        assert cleaned_data.get("is_resume_mandatory")

        del post_data["is_resume_mandatory"]

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data
        assert not cleaned_data.get("is_resume_mandatory")

    def test_opcs_fields(self):
        siae = SiaeFactory(kind=CompanyKind.OPCS)

        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": "on",
            "is_qpv_mandatory": "on",
        }

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data

        assert "description" == cleaned_data.get("description")
        assert "profile_description" == cleaned_data.get("profile_description")

        # Checkboxes status
        assert cleaned_data.get("is_resume_mandatory")
        assert cleaned_data.get("is_qpv_mandatory")

        del post_data["is_resume_mandatory"]
        del post_data["is_qpv_mandatory"]

        form = EditJobDescriptionDetailsForm(current_siae=siae, data=post_data)

        assert form.is_valid()

        cleaned_data = form.cleaned_data
        assert not cleaned_data.get("is_resume_mandatory")
        assert not cleaned_data.get("is_qpv_mandatory")
