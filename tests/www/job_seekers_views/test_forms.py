from itou.www.job_seekers_views import forms as job_seekers_forms
from tests.users.factories import (
    JobSeekerFactory,
    JobSeekerProfileFactory,
    PrescriberFactory,
)


class TestCheckJobSeekerNirForm:
    def test_form_job_seeker_not_found(self):
        # This NIR is unique.
        nir = JobSeekerProfileFactory.build().nir
        form_data = {"nir": nir}
        form = job_seekers_forms.CheckJobSeekerNirForm(data=form_data)
        assert form.is_valid()
        assert form.job_seeker is None

    def test_form_job_seeker_found(self):
        # A job seeker with this NIR already exists.
        nir = "141062A78200555"
        job_seeker = JobSeekerFactory(jobseeker_profile__nir=nir)
        form_data = {"nir": job_seeker.jobseeker_profile.nir}
        form = job_seekers_forms.CheckJobSeekerNirForm(data=form_data)
        # A job seeker has been found.
        assert form.is_valid()
        assert form.job_seeker == job_seeker

        # NIR should be case insensitive.
        form_data = {"nir": job_seeker.jobseeker_profile.nir.lower()}
        form = job_seekers_forms.CheckJobSeekerNirForm(data=form_data)
        # A job seeker has been found.
        assert form.is_valid()
        assert form.job_seeker == job_seeker

    def test_form_not_valid(self):
        # Application sent by a job seeker whose NIR is already used by another account.
        existing_account = JobSeekerFactory(email="unlikely@random.tld")
        user = JobSeekerFactory()
        form_data = {"nir": existing_account.jobseeker_profile.nir}
        form = job_seekers_forms.CheckJobSeekerNirForm(job_seeker=user, data=form_data)
        assert not form.is_valid()
        error_msg = form.errors["nir"][0]
        assert "Ce numéro de sécurité sociale est déjà utilisé par un autre compte." in error_msg
        assert existing_account.email not in error_msg
        assert "u*******@r*****.t**" in error_msg

        existing_account = PrescriberFactory()
        profile = JobSeekerProfileFactory(user=existing_account)  # This should not be possible
        form_data = {"nir": profile.nir}
        form = job_seekers_forms.CheckJobSeekerNirForm(data=form_data)
        assert not form.is_valid()
        assert (
            "Vous ne pouvez postuler pour cet utilisateur car ce numéro de sécurité sociale "
            "n'est pas associé à un compte candidat."
        ) == form.errors["__all__"][0]


class TestCreateOrUpdateJobSeekerStep1Form:
    def test_commune_birthdate_dependency(self):
        form = job_seekers_forms.CreateOrUpdateJobSeekerStep1Form()
        assert form.with_birthdate_field
