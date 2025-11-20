import random
from datetime import date, timedelta
from functools import partial
from unittest.mock import call

from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time

from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind
from itou.eligibility.models.iae import AdministrativeCriteria
from itou.job_applications.enums import JobApplicationState
from tests.eligibility.factories import IAESelectedAdministrativeCriteriaFactory
from tests.job_applications.factories import JobApplicationFactory


class TestRetryCertifyCriteria:
    def test_identifies_criteria_to_retry(self, mocker):
        certify_criterion_task = mocker.patch(
            "itou.eligibility.management.commands.retry_certify_criteria.async_certify_criterion_with_api_particulier",
            autospec=True,
        )
        factory = partial(IAESelectedAdministrativeCriteriaFactory, eligibility_diagnosis__certifiable=True)
        # Just created, ignored.
        factory(criteria_certification_error=True)
        to_retry = []
        with freeze_time(timezone.now() - timedelta(days=2)):
            factory(criteria_certified=True)
            factory(criteria_not_certified=True)
            other_criteria_kinds = AdministrativeCriteriaKind.common() - CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS
            not_retryable_kind = random.choice(list(other_criteria_kinds))
            factory(administrative_criteria=AdministrativeCriteria.objects.get(kind=not_retryable_kind))
            factory(criteria_certification_error=True, eligibility_diagnosis__expires_at=date(2023, 1, 1))
            crit_with_accepted_job_app = factory(criteria_certification_error=True)
            JobApplicationFactory(
                eligibility_diagnosis=crit_with_accepted_job_app.eligibility_diagnosis,
                state=JobApplicationState.ACCEPTED,
            )

            to_retry.append(factory(criteria_certification_error=True))
            crit_with_job_app = factory(criteria_certification_error=True)
            JobApplicationFactory(eligibility_diagnosis=crit_with_job_app.eligibility_diagnosis)
            to_retry.append(crit_with_job_app)

        call_command("retry_certify_criteria", wet_run=True)
        expected_retries = [call(crit._meta.model_name, crit.pk) for crit in to_retry]
        assert certify_criterion_task.mock_calls == expected_retries

    def test_wet_run(self, mocker):
        certify_criterion_task = mocker.patch(
            "itou.eligibility.management.commands.retry_certify_criteria.async_certify_criterion_with_api_particulier",
            autospec=True,
        )
        with freeze_time(timezone.now() - timedelta(days=2)):
            IAESelectedAdministrativeCriteriaFactory(
                criteria_certification_error=True, eligibility_diagnosis__certifiable=True
            )
        call_command("retry_certify_criteria", wet_run=False)
        certify_criterion_task.assert_not_called()
        call_command("retry_certify_criteria", wet_run=True)
        certify_criterion_task.assert_called()
