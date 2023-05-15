from datetime import datetime

import pytest
from django.urls import reverse
from faker import Faker
from pytest_django.asserts import assertContains, assertNotContains

from itou.job_applications.enums import QualificationLevel, QualificationType
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentBySiaeFactory,
)
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.enums import ContractType, SiaeKind
from itou.users.factories import JobSeekerFactory, PrescriberFactory
from itou.utils.test import TestCase
from itou.www.apply import forms as apply_forms


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
        existing_account = JobSeekerFactory()
        user = JobSeekerFactory()
        form_data = {"nir": existing_account.nir}
        form = apply_forms.CheckJobSeekerNirForm(job_seeker=user, data=form_data)
        assert not form.is_valid()
        assert "Ce numéro de sécurité sociale est déjà utilisé par un autre compte." in form.errors["nir"][0]

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

        job_application = JobApplicationSentBySiaeFactory()
        form = apply_forms.RefusalForm(job_application=job_application)
        assert "answer_to_prescriber" not in form.fields.keys()


@pytest.mark.usefixtures("unittest_compatibility")
class JobApplicationAcceptFormWithGEIQFieldsTest(TestCase):
    def test_accept_form_without_geiq(self):
        # Job application accept form for a "standard" SIAE
        form = apply_forms.AcceptForm(instance=JobApplicationFactory(to_siae__kind=SiaeKind.EI))

        assert list(form.fields.keys()) == ["hiring_start_at", "hiring_end_at", "answer"]
        # Nothing more to see, move on...

    def test_accept_form_with_geiq(self):
        # Job application accept form for a GEIQ: more fields
        form = apply_forms.AcceptForm(instance=JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ))

        assert sorted(form.fields.keys()) == [
            "answer",
            "contract_type",
            "contract_type_details",
            "hiring_end_at",
            "hiring_start_at",
            "nb_hours_per_week",
            "planned_training_days",
            "prehiring_guidance_days",
            "qualification_level",
            "qualification_type",
        ]

        # Dynamic contract type details field
        form = apply_forms.AcceptForm(
            instance=JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ), data={"contract_type": ContractType.OTHER}
        )
        assert sorted(form.fields.keys()) == [
            "answer",
            "contract_type",
            "contract_type_details",
            "hiring_end_at",
            "hiring_start_at",
            "nb_hours_per_week",
            "planned_training_days",
            "prehiring_guidance_days",
            "qualification_level",
            "qualification_type",
        ]

    def test_accept_form_geiq_required_fields_validation(self):
        job_application = JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ)

        post_data = {"hiring_start_at": f"{datetime.now():%Y-%m-%d}"}
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)
        sorted_errors = dict(sorted(form.errors.items()))
        assert sorted_errors == {
            "contract_type": ["Ce champ est obligatoire."],
            "nb_hours_per_week": ["Ce champ est obligatoire."],
            "planned_training_days": ["Ce champ est obligatoire."],
            "prehiring_guidance_days": ["Ce champ est obligatoire."],
            "qualification_level": ["Ce champ est obligatoire."],
            "qualification_type": ["Ce champ est obligatoire."],
        }

        post_data |= {"prehiring_guidance_days": self.faker.pyint()}
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)
        sorted_errors = dict(sorted(form.errors.items()))
        assert sorted_errors == {
            "contract_type": ["Ce champ est obligatoire."],
            "nb_hours_per_week": ["Ce champ est obligatoire."],
            "planned_training_days": ["Ce champ est obligatoire."],
            "qualification_level": ["Ce champ est obligatoire."],
            "qualification_type": ["Ce champ est obligatoire."],
        }

        post_data |= {"contract_type": ContractType.APPRENTICESHIP}
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)
        sorted_errors = dict(sorted(form.errors.items()))
        assert sorted_errors == {
            "nb_hours_per_week": ["Ce champ est obligatoire."],
            "planned_training_days": ["Ce champ est obligatoire."],
            "qualification_level": ["Ce champ est obligatoire."],
            "qualification_type": ["Ce champ est obligatoire."],
        }

        post_data |= {
            "nb_hours_per_week": 35,
            "qualification_type": QualificationType.CCN,
            "qualification_level": QualificationLevel.LEVEL_4,
            "planned_training_days": self.faker.pyint(),
        }
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)
        assert form.is_valid()

    def test_accept_form_geiq_contract_type_field_validation(self):
        job_application = JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ)
        post_data = {
            "hiring_start_at": f"{datetime.now():%Y-%m-%d}",
            "prehiring_guidance_days": self.faker.pyint(),
            "nb_hours_per_week": 35,
        }

        # ContractType.OTHER ask for more details
        form = apply_forms.AcceptForm(instance=job_application, data=post_data | {"contract_type": ContractType.OTHER})

        assert form.errors == {
            "contract_type_details": ["Les précisions sont nécessaires pour ce type de contrat"],
            "planned_training_days": ["Ce champ est obligatoire."],
            "qualification_level": ["Ce champ est obligatoire."],
            "qualification_type": ["Ce champ est obligatoire."],
        }

        form = apply_forms.AcceptForm(
            instance=job_application,
            data=post_data
            | {
                "contract_type": ContractType.OTHER,
                "contract_type_details": "foo",
                "qualification_type": QualificationType.CQP,
                "qualification_level": QualificationLevel.LEVEL_3,
                "planned_training_days": self.faker.pyint(),
            },
        )
        assert form.is_valid()

        # ContractType.APPRENTICESHIP doesn't ask for more details
        form = apply_forms.AcceptForm(
            instance=job_application,
            data=post_data
            | {
                "contract_type": ContractType.APPRENTICESHIP,
                "qualification_type": QualificationType.CCN,
                "qualification_level": QualificationLevel.LEVEL_4,
                "planned_training_days": self.faker.pyint(),
                "nb_of_hours_per_week": self.faker.pyint(),
            },
        )
        assert form.is_valid()

        # ContractType.PROFESSIONAL_TRAINING doesn't ask for more details
        form = apply_forms.AcceptForm(
            instance=job_application,
            data=post_data
            | {
                "contract_type": ContractType.PROFESSIONAL_TRAINING,
                "qualification_type": QualificationType.CCN,
                "qualification_level": QualificationLevel.NOT_RELEVANT,
                "planned_training_days": self.faker.pyint(),
                "nb_of_hours_per_week": self.faker.pyint(),
            },
        )
        assert form.is_valid()

    def test_save_geiq_form_fields_from_view(self):
        # non-GEIQ accept case tests are in `tests_process.py`
        job_application = JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, state="processing")
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(job_application.to_siae.members.first())

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
            "planned_training_days": self.faker.pyint(),
            "answer": "foo",
            "confirmed": "True",
        }

        response = self.client.post(url_accept, HTTP_HX_REQUEST=True, data=post_data, follow=True)

        # See https://django-htmx.readthedocs.io/en/latest/http.html#django_htmx.http.HttpResponseClientRedirect # noqa
        assert response.status_code == 200

        job_application.refresh_from_db()

        assert f"{job_application.hiring_start_at:%Y-%m-%d}" == post_data["hiring_start_at"]
        assert f"{job_application.hiring_end_at:%Y-%m-%d}" == post_data["hiring_end_at"]
        assert job_application.answer == post_data["answer"]
        assert job_application.contract_type == post_data["contract_type"]
        assert job_application.contract_type_details == post_data["contract_type_details"]
        assert job_application.nb_hours_per_week == post_data["nb_hours_per_week"]

    def test_apply_with_past_hiring_date(self):
        # GEIQ can temporarily accept job applications with a past hiring date

        # with a SIAE
        job_application = JobApplicationFactory(to_siae__kind=SiaeKind.EI, state="processing")
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(job_application.to_siae.members.first())

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
            "planned_training_days": self.faker.pyint(),
            "answer": "foobar",
            "confirmed": "True",
        }

        response = self.client.post(url_accept, HTTP_HX_REQUEST=True, data=post_data, follow=True)

        assert response.status_code == 200
        assertContains(response, "Il n'est pas possible d'antidater un contrat.")
        # Testing a redirect with HTMX is really incomplete, so we also check hiring status
        job_application.refresh_from_db()
        assert job_application.state == JobApplicationWorkflow.STATE_PROCESSING

        # with a GEIQ
        job_application = JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ, state="processing")
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        self.client.force_login(job_application.to_siae.members.first())
        response = self.client.post(url_accept, HTTP_HX_REQUEST=True, data=post_data, follow=True)

        assert response.status_code == 200
        assertNotContains(response, "Il n'est pas possible d'antidater un contrat.")
        job_application.refresh_from_db()
        assert job_application.state == JobApplicationWorkflow.STATE_ACCEPTED
