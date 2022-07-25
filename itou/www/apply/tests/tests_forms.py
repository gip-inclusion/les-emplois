from django.test import TestCase

from itou.job_applications.factories import (
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
    JobApplicationSentBySiaeFactory,
)
from itou.users.factories import JobSeekerFactory
from itou.www.apply import forms as apply_forms


class CheckJobSeekerNirFormTest(TestCase):
    def test_form_job_seeker_not_found(self):
        # This NIR is unique.
        nir = JobSeekerFactory.build().nir
        form_data = {"nir": nir}
        form = apply_forms.CheckJobSeekerNirForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.job_seeker)

    def test_form_job_seeker_found(self):
        # A job seeker with this NIR already exists.
        nir = "141062A78200555"
        job_seeker = JobSeekerFactory(nir=nir)
        form_data = {"nir": job_seeker.nir}
        form = apply_forms.CheckJobSeekerNirForm(data=form_data)
        # A job seeker has been found.
        self.assertTrue(form.is_valid())
        self.assertEqual(form.job_seeker, job_seeker)

        # NIR should be case insensitive.
        form_data = {"nir": job_seeker.nir.lower()}
        form = apply_forms.CheckJobSeekerNirForm(data=form_data)
        # A job seeker has been found.
        self.assertTrue(form.is_valid())
        self.assertEqual(form.job_seeker, job_seeker)

    def test_form_not_valid(self):
        # Application sent by a job seeker whose NIR is already used by another account.
        existing_account = JobSeekerFactory()
        user = JobSeekerFactory()
        form_data = {"nir": existing_account.nir}
        form = apply_forms.CheckJobSeekerNirForm(job_seeker=user, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Ce numéro de sécurité sociale est déjà utilisé par un autre compte.", form.errors["nir"][0])


class RefusalFormTest(TestCase):
    def test_job_application_sent_by_prescriber(self):
        job_application = JobApplicationSentByPrescriberFactory()
        form = apply_forms.RefusalForm(job_application=job_application)
        self.assertIn("answer_to_prescriber", form.fields.keys())

    def test_job_application_not_sent_by_prescriber(self):
        job_application = JobApplicationSentByJobSeekerFactory()
        form = apply_forms.RefusalForm(job_application=job_application)
        self.assertNotIn("answer_to_prescriber", form.fields.keys())

        job_application = JobApplicationSentBySiaeFactory()
        form = apply_forms.RefusalForm(job_application=job_application)
        self.assertNotIn("answer_to_prescriber", form.fields.keys())
