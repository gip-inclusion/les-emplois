from itou.job_applications.factories import (
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentBySiaeFactory,
)
from itou.users.factories import JobSeekerFactory
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
