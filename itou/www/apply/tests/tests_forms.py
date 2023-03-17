from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.urls import reverse

from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentBySiaeFactory,
)
from itou.siaes.enums import ContractType, SiaeKind
from itou.users.factories import JobSeekerFactory, PrescriberFactory
from itou.utils.test import TestCase
from itou.www.apply import forms as apply_forms


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
            "est assicé à un prescripteur ou à un employeur."
        ) == form.errors["nir"][0]


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


class JobApplicationAcceptFormWithGEIQFieldsTest(TestCase):
    def test_accept_form_without_geiq(self):
        # Job application accept form for a "standard" SIAE
        form = apply_forms.AcceptForm(instance=JobApplicationFactory(to_siae__kind=SiaeKind.EI))

        assert list(form.fields.keys()) == ["hiring_start_at", "hiring_end_at", "answer"]
        # Nothing more to see, move on...

    def test_accept_form_with_geiq(self):
        # Job application accept form for a GEIQ: more fields
        form = apply_forms.AcceptForm(instance=JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ))

        assert list(form.fields.keys()) == [
            "contract_type",
            "contract_type_details",
            "nb_hours_per_week",
            "hiring_start_at",
            "hiring_end_at",
            "answer",
        ]

        # Dynamic contract type details field
        form = apply_forms.AcceptForm(
            instance=JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ), data={"contract_type": ContractType.OTHER}
        )
        assert list(form.fields.keys()) == [
            "contract_type",
            "contract_type_details",
            "nb_hours_per_week",
            "hiring_start_at",
            "hiring_end_at",
            "answer",
        ]

    def test_accept_form_geiq_fields_validation(self):
        job_application = JobApplicationFactory(to_siae__kind=SiaeKind.GEIQ)
        post_data = {"hiring_start_at": f"{datetime.now():%Y-%m-%d}"}
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)

        assert form.errors == {
            "contract_type": ["Ce champ est obligatoire."],
            "nb_hours_per_week": ["Ce champ est obligatoire."],
        }

        post_data |= {"contract_type": ContractType.APPRENTICESHIP}
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)

        assert form.errors == {
            "nb_hours_per_week": ["Ce champ est obligatoire."],
        }

        post_data |= {"contract_type": ContractType.OTHER}
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)

        assert form.errors == {
            "nb_hours_per_week": ["Ce champ est obligatoire."],
            "contract_type_details": ["Les précisions sont nécessaires pour ce type de contrat"],
        }

        post_data |= {"nb_hours_per_week": 35, "contract_type": ContractType.PROFESSIONAL_TRAINING}
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)

        assert form.is_valid()

        post_data |= {"nb_hours_per_week": 20, "contract_type": ContractType.OTHER, "contract_type_details": "foo"}
        form = apply_forms.AcceptForm(instance=job_application, data=post_data)

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
            "hiring_end_at": f"{datetime.now() + relativedelta(months=3):%Y-%m-%d}",
            "nb_hours_per_week": 4,
            "contract_type_details": "contract details",
            "contract_type": str(ContractType.OTHER),
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
