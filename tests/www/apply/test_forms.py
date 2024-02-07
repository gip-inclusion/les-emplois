from datetime import datetime

import pytest
from django.urls import reverse
from faker import Faker
from pytest_django.asserts import assertContains, assertNotContains

from itou.cities.models import City
from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS, CompanyKind, ContractType
from itou.job_applications.enums import QualificationLevel, QualificationType
from itou.job_applications.models import JobApplicationWorkflow
from itou.www.apply import forms as apply_forms
from tests.cities.factories import create_test_cities
from tests.companies.factories import JobDescriptionFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByCompanyFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.test import TestCase


faker = Faker()


class CheckJobSeekerNirFormTest(TestCase):
    def test_form_job_seeker_not_found(self):
        # This NIR is unique.
        nir = JobSeekerFactory.build().nir
        form_data = {"nir": nir}
        form = apply_forms.CheckJobSeekerNirForm(data=form_data)
        assert form.is_valid()
        assert form.job_seeker is None

    def test_form_job_seeker_found(self):
        # A job seeker with this NIR already exists.
        nir = "141062A78200555"
        job_seeker = JobSeekerFactory(nir=nir)
        form_data = {"nir": job_seeker.nir}
        form = apply_forms.CheckJobSeekerNirForm(data=form_data)
        # A job seeker has been found.
        assert form.is_valid()
        assert form.job_seeker == job_seeker

        # NIR should be case insensitive.
        form_data = {"nir": job_seeker.nir.lower()}
        form = apply_forms.CheckJobSeekerNirForm(data=form_data)
        # A job seeker has been found.
        assert form.is_valid()
        assert form.job_seeker == job_seeker

    def test_form_not_valid(self):
        # Application sent by a job seeker whose NIR is already used by another account.
        existing_account = JobSeekerFactory(email="unlikely@random.tld")
        user = JobSeekerFactory()
        form_data = {"nir": existing_account.nir}
        form = apply_forms.CheckJobSeekerNirForm(job_seeker=user, data=form_data)
        assert not form.is_valid()
        error_msg = form.errors["nir"][0]
        assert "Ce numéro de sécurité sociale est déjà utilisé par un autre compte." in error_msg
        assert existing_account.email not in error_msg
        assert "u*******@r*****.t**" in error_msg

        existing_account = PrescriberFactory(nir=JobSeekerFactory.build().nir)
        form_data = {"nir": existing_account.nir}
        form = apply_forms.CheckJobSeekerNirForm(data=form_data)
        assert not form.is_valid()
        assert (
            "Vous ne pouvez postuler pour cet utilisateur car ce numéro de sécurité sociale "
            "n'est pas associé à un compte candidat."
        ) == form.errors["__all__"][0]


class RefusalFormTest(TestCase):
    def test_job_application_sent_by_prescriber(self):
        job_application = JobApplicationSentByPrescriberFactory()
        form = apply_forms.RefusalForm(job_application=job_application)
        assert "answer_to_prescriber" in form.fields.keys()

    def test_job_application_not_sent_by_prescriber(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        form = apply_forms.RefusalForm(job_application=job_application)
        assert "answer_to_prescriber" not in form.fields.keys()

        job_application = JobApplicationSentByCompanyFactory()
        form = apply_forms.RefusalForm(job_application=job_application)
        assert "answer_to_prescriber" not in form.fields.keys()


class TestAcceptForm:
    def test_accept_form_without_geiq(self):
        # Job application accept form for a "standard" SIAE
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.EI)
        form = apply_forms.AcceptForm(company=job_application.to_company)

        assert sorted(form.fields.keys()) == [
            "answer",
            "appellation",
            "hired_job",
            "hiring_end_at",
            "hiring_start_at",
            "location",
        ]
        # Nothing more to see, move on...

    def test_accept_form_with_geiq(self):
        EXPECTED_FIELDS = [
            "answer",
            "appellation",
            "contract_type",
            "contract_type_details",
            "hired_job",
            "hiring_end_at",
            "hiring_start_at",
            "inverted_vae_contract",
            "location",
            "nb_hours_per_week",
            "planned_training_hours",
            "prehiring_guidance_days",
            "qualification_level",
            "qualification_type",
        ]
        # Job application accept form for a GEIQ: more fields
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)
        form = apply_forms.AcceptForm(company=job_application.to_company)

        assert sorted(form.fields.keys()) == EXPECTED_FIELDS

        # Dynamic contract type details field
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)
        form = apply_forms.AcceptForm(
            company=job_application.to_company,
            data={"contract_type": ContractType.OTHER},
        )
        assert sorted(form.fields.keys()) == EXPECTED_FIELDS

    def test_accept_form_geiq_required_fields_validation(self, faker):
        [city] = create_test_cities(["54"], num_per_department=1)
        create_test_romes_and_appellations(["N4105"], appellations_per_rome=2)
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)
        job_description = JobDescriptionFactory(company=job_application.to_company, location=None)
        post_data = {"hiring_start_at": f"{datetime.now():%Y-%m-%d}"}
        form = apply_forms.AcceptForm(company=job_application.to_company, data=post_data)
        sorted_errors = dict(sorted(form.errors.items()))
        assert sorted_errors == {
            "contract_type": ["Ce champ est obligatoire."],
            "nb_hours_per_week": ["Ce champ est obligatoire."],
            "hired_job": ["Ce champ est obligatoire."],
            "planned_training_hours": ["Ce champ est obligatoire."],
            "prehiring_guidance_days": ["Ce champ est obligatoire."],
            "qualification_level": ["Ce champ est obligatoire."],
            "qualification_type": ["Ce champ est obligatoire."],
        }

        post_data |= {"prehiring_guidance_days": faker.pyint()}
        form = apply_forms.AcceptForm(company=job_application.to_company, data=post_data)
        sorted_errors = dict(sorted(form.errors.items()))
        assert sorted_errors == {
            "contract_type": ["Ce champ est obligatoire."],
            "nb_hours_per_week": ["Ce champ est obligatoire."],
            "hired_job": ["Ce champ est obligatoire."],
            "planned_training_hours": ["Ce champ est obligatoire."],
            "qualification_level": ["Ce champ est obligatoire."],
            "qualification_type": ["Ce champ est obligatoire."],
        }

        # Add job related fields
        post_data |= {"hired_job": job_description.pk, "location": city.pk}

        post_data |= {"contract_type": ContractType.APPRENTICESHIP}
        form = apply_forms.AcceptForm(company=job_application.to_company, data=post_data)
        sorted_errors = dict(sorted(form.errors.items()))
        assert sorted_errors == {
            "nb_hours_per_week": ["Ce champ est obligatoire."],
            "planned_training_hours": ["Ce champ est obligatoire."],
            "qualification_level": ["Ce champ est obligatoire."],
            "qualification_type": ["Ce champ est obligatoire."],
        }

        post_data |= {
            "nb_hours_per_week": 35,
            "qualification_type": QualificationType.CCN,
            "qualification_level": QualificationLevel.LEVEL_4,
            "planned_training_hours": faker.pyint(),
            "contract_type": ContractType.PROFESSIONAL_TRAINING,
        }
        form = apply_forms.AcceptForm(company=job_application.to_company, data=post_data)
        assert form.is_valid()

    def test_accept_form_geiq_contract_type_field_validation(self, faker):
        create_test_romes_and_appellations(["N4105"], appellations_per_rome=2)
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)
        job_description = JobDescriptionFactory(company=job_application.to_company)
        post_data = {
            "hiring_start_at": f"{datetime.now():%Y-%m-%d}",
            "prehiring_guidance_days": faker.pyint(),
            "nb_hours_per_week": 35,
            "hired_job": job_description.pk,
        }

        # ContractType.OTHER ask for more details
        form = apply_forms.AcceptForm(
            company=job_application.to_company, data=post_data | {"contract_type": ContractType.OTHER}
        )

        sorted_errors = dict(sorted(form.errors.items()))
        assert sorted_errors == {
            "contract_type_details": ["Les précisions sont nécessaires pour ce type de contrat"],
            "planned_training_hours": ["Ce champ est obligatoire."],
            "qualification_level": ["Ce champ est obligatoire."],
            "qualification_type": ["Ce champ est obligatoire."],
        }

        form = apply_forms.AcceptForm(
            company=job_application.to_company,
            data=post_data
            | {
                "contract_type": ContractType.OTHER,
                "contract_type_details": "foo",
                "qualification_type": QualificationType.CQP,
                "qualification_level": QualificationLevel.LEVEL_3,
                "planned_training_hours": faker.pyint(),
            },
        )

        assert form.is_valid()

        # ContractType.APPRENTICESHIP doesn't ask for more details
        form = apply_forms.AcceptForm(
            company=job_application.to_company,
            data=post_data
            | {
                "contract_type": ContractType.APPRENTICESHIP,
                "qualification_type": QualificationType.CCN,
                "qualification_level": QualificationLevel.LEVEL_4,
                "planned_training_hours": faker.pyint(),
                "nb_of_hours_per_week": faker.pyint(),
            },
        )
        assert form.is_valid()

        # ContractType.PROFESSIONAL_TRAINING doesn't ask for more details
        form = apply_forms.AcceptForm(
            company=job_application.to_company,
            data=post_data
            | {
                "contract_type": ContractType.PROFESSIONAL_TRAINING,
                "qualification_type": QualificationType.CCN,
                "qualification_level": QualificationLevel.NOT_RELEVANT,
                "planned_training_hours": faker.pyint(),
                "nb_of_hours_per_week": faker.pyint(),
            },
        )
        assert form.is_valid()


@pytest.mark.usefixtures("unittest_compatibility")
class JobApplicationAcceptFormWithGEIQFieldsTest(TestCase):
    def test_save_geiq_form_fields_from_view(self):
        # non-GEIQ accept case tests are in `tests_process.py`
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        create_test_cities(["54", "57"], num_per_department=2)

        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, state="processing")
        job_description = JobDescriptionFactory(company=job_application.to_company)
        city = City.objects.order_by("?").first()
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(job_application.to_company.members.first())

        response = self.client.get(url_accept)
        assert response.status_code == 200

        post_data = {
            "hiring_start_at": f"{datetime.now():%Y-%m-%d}",
            "hiring_end_at": f"{faker.future_date(end_date='+3M'):%Y-%m-%d}",
            "prehiring_guidance_days": self.faker.pyint(),
            "nb_hours_per_week": 4,
            "contract_type_details": "contract details",
            "contract_type": str(ContractType.OTHER),
            "qualification_type": QualificationType.CCN,
            "qualification_level": QualificationLevel.NOT_RELEVANT,
            "planned_training_hours": self.faker.pyint(),
            "location": city.pk,
            "answer": "foo",
            "hired_job": job_description.pk,
            "confirmed": True,
        }

        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data, follow=True)

        # See https://django-htmx.readthedocs.io/en/latest/http.html#django_htmx.http.HttpResponseClientRedirect # noqa
        assert response.status_code == 200

        job_application.refresh_from_db()

        assert f"{job_application.hiring_start_at:%Y-%m-%d}" == post_data["hiring_start_at"]
        assert f"{job_application.hiring_end_at:%Y-%m-%d}" == post_data["hiring_end_at"]
        assert job_application.answer == post_data["answer"]
        assert job_application.contract_type == post_data["contract_type"]
        assert job_application.contract_type_details == post_data["contract_type_details"]
        assert job_application.nb_hours_per_week == post_data["nb_hours_per_week"]
        assert job_application.qualification_level == post_data["qualification_level"]
        assert job_application.qualification_type == post_data["qualification_type"]
        assert not job_application.inverted_vae_contract

    def test_geiq_inverted_vae_fields(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, state="processing")
        job_description = JobDescriptionFactory(company=job_application.to_company)
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(job_application.to_company.members.first())

        response = self.client.get(url_accept)
        assert response.status_code == 200

        post_data = {
            "hiring_start_at": f"{datetime.now():%Y-%m-%d}",
            "hiring_end_at": f"{faker.future_date(end_date='+3M'):%Y-%m-%d}",
            "hired_job": job_description.pk,
            "prehiring_guidance_days": self.faker.pyint(),
            "nb_hours_per_week": 4,
            "contract_type_details": "",
            "contract_type": str(ContractType.PROFESSIONAL_TRAINING),
            "inverted_vae_contract": "on",
            "qualification_type": QualificationType.CCN,
            "qualification_level": QualificationLevel.NOT_RELEVANT,
            "planned_training_hours": self.faker.pyint(),
            "answer": "foo",
            "confirmed": "True",
        }

        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data, follow=True)
        assert response.status_code == 200

        job_application.refresh_from_db()
        assert job_application.contract_type == post_data["contract_type"]
        assert job_application.contract_type_details == post_data["contract_type_details"]
        assert job_application.inverted_vae_contract

    def test_apply_with_past_hiring_date(self):
        CANNOT_BACKDATE_TEXT = "Il n'est pas possible d'antidater un contrat."
        # GEIQ can temporarily accept job applications with a past hiring date
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))

        # with a SIAE
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.EI, state="processing")
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(job_application.to_company.members.first())

        response = self.client.get(url_accept)
        assert response.status_code == 200

        post_data = {
            "hiring_start_at": f"{faker.past_date(start_date='-1d'):%Y-%m-%d}",
            "hiring_end_at": f"{faker.future_date(end_date='+3M'):%Y-%m-%d}",
            "prehiring_guidance_days": self.faker.pyint(),
            "nb_hours_per_week": 5,
            "contract_type_details": "contract details",
            "contract_type": str(ContractType.OTHER),
            "qualification_type": QualificationType.CCN,
            "qualification_level": QualificationLevel.LEVEL_4,
            "planned_training_hours": self.faker.pyint(),
            "answer": "foobar",
            "confirmed": "True",
        }

        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data, follow=True)

        assert response.status_code == 200
        assertContains(response, CANNOT_BACKDATE_TEXT)
        # Testing a redirect with HTMX is really incomplete, so we also check hiring status
        job_application.refresh_from_db()
        assert job_application.state == JobApplicationWorkflow.STATE_PROCESSING

        # with a GEIQ
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ, state="processing")
        job_description = JobDescriptionFactory(company=job_application.to_company)
        post_data |= {"hired_job": job_description.pk}

        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        self.client.force_login(job_application.to_company.members.first())
        response = self.client.post(url_accept, headers={"hx-request": "true"}, data=post_data, follow=True)

        assert response.status_code == 200
        assertNotContains(response, CANNOT_BACKDATE_TEXT)
        job_application.refresh_from_db()
        assert job_application.state == JobApplicationWorkflow.STATE_ACCEPTED

    HELP_START_AT = (
        "La date est modifiable jusqu'à la veille de la date saisie. "
        "En cas de premier PASS IAE pour la personne, cette date déclenche le début de son parcours."
    )
    HELP_END_AT = (
        "Elle sert uniquement à des fins d'informations et est sans conséquence sur les déclarations "
        "à faire dans l'extranet 2.0 de l'ASP. "
        "<b>Ne pas compléter cette date dans le cadre d’un CDI Inclusion</b>"
    )

    def test_specific_iae_mentions_in_accept_form(self):
        def _response(kind):
            job_application = JobApplicationFactory(to_company__kind=kind, state="processing")
            url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

            self.client.force_login(job_application.to_company.members.first())
            response = self.client.get(url_accept)

            assert response.status_code == 200
            return response

        for kind in SIAE_WITH_CONVENTION_KINDS:
            assertContains(_response(kind), self.HELP_START_AT)
            assertContains(_response(kind), self.HELP_END_AT)

        for kind in (CompanyKind.EA, CompanyKind.EATT, CompanyKind.GEIQ, CompanyKind.OPCS):
            assertNotContains(_response(kind), self.HELP_START_AT)
            assertNotContains(_response(kind), self.HELP_END_AT)
