import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from itou.archive.models import ArchivedJobSeeker
from itou.users.models import User
from tests.users.factories import JobSeekerFactory


class TestArchiveJobSeekersManagementCommand:
    def test_dry_run_does_not_archive_jobseekers(self):
        pass

    def test_batch_size(self):
        pass

    @pytest.mark.parametrize(
        "name,kwargs",
        [
            (
                "jobseeker_with_jobseeker_profile_and_all_datas",
                {
                    "first_login": timezone.now(),
                    "last_login": timezone.now(),
                    # "created_by__kind": UserKind.PRESCRIBER, # TO BE FIXED
                    "jobseeker_profile__pole_emploi_id": "12345678",
                    "jobseeker_profile__nir": "855456789012345",
                    "jobseeker_profile__lack_of_nir_reason": "",
                    "jobseeker_profile__birthdate": datetime.date(1990, 1, 1),
                },
            ),
            (
                "jobseeker_with_jobseeker_profile_and_very_few_datas",
                {
                    "first_login": None,
                    "last_login": None,
                    "created_by": None,
                    "jobseeker_profile__pole_emploi_id": "",
                    "jobseeker_profile__nir": "",
                    "jobseeker_profile__lack_of_nir_reason": "reason",
                    "jobseeker_profile__birthdate": None,
                },
            ),
            ("jobseeker_without_jobseeker_profile", {"jobseeker_profile": None}),
        ],
    )
    def test_datas_after_anonimisation(
        self,
        name,
        kwargs,
        django_capture_on_commit_callbacks,
    ):
        jobseeker = JobSeekerFactory(is_active=False, upcoming_deletion_notified_at=timezone.now(), **kwargs)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("archive_jobseekers", wet_run=True)

        assert User.objects.filter(id=jobseeker.id).exists() is False

        archived_jobseeker = ArchivedJobSeeker.objects.get()
        assert archived_jobseeker.date_joined == jobseeker.date_joined.date()
        assert archived_jobseeker.first_login == (jobseeker.first_login.date() if jobseeker.first_login else None)
        assert archived_jobseeker.last_login == (jobseeker.last_login.date() if jobseeker.last_login else None)
        assert archived_jobseeker.user_signup_kind == (jobseeker.created_by.kind if jobseeker.created_by else None)
        assert archived_jobseeker.department == jobseeker.department
        assert archived_jobseeker.title == jobseeker.title
        assert archived_jobseeker.identity_provider == jobseeker.identity_provider
        assert archived_jobseeker.kind == jobseeker.kind

        if hasattr(jobseeker, "jobseeker_profile"):
            assert archived_jobseeker.had_pole_emploi_id == bool(jobseeker.jobseeker_profile.pole_emploi_id)
            assert archived_jobseeker.had_nir == bool(jobseeker.jobseeker_profile.nir)
            assert archived_jobseeker.lack_of_nir_reason == jobseeker.jobseeker_profile.lack_of_nir_reason
            assert archived_jobseeker.nir_sex == (
                jobseeker.jobseeker_profile.nir[0] if jobseeker.jobseeker_profile.nir else None
            )
            assert archived_jobseeker.nir_year == (
                int(jobseeker.jobseeker_profile.nir[1:3]) if jobseeker.jobseeker_profile.nir else None
            )
            assert archived_jobseeker.birth_year == (
                int(jobseeker.jobseeker_profile.birthdate.year) if jobseeker.jobseeker_profile.birthdate else None
            )
