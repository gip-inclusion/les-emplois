from django.core.management import call_command

from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory
from tests.users.factories import EmployerFactory, JobSeekerProfileFactory


def test_no_inconsistencies_no_slack(caplog):
    call_command("check_inconsistencies")
    assert "Found 0 inconsistencies but no slack webhook configured" in caplog.text
    # Check that an error was logged & sent to Sentry
    assert "ERROR" in [record.levelname for record in caplog.records]


def test_no_inconsistencies_with_slack_webhook(caplog, settings, mocker):
    slack_mock = mocker.patch("itou.utils.management.commands.check_inconsistencies.send_slack_message")
    settings.SLACK_INCONSISTENCIES_WEBHOOK_URL = "http://slack.fake"
    call_command("check_inconsistencies")

    assert slack_mock.mock_calls == [
        mocker.call(
            text="0 incohérence trouvée:\nBon boulot :not-bad:",
            url=settings.SLACK_INCONSISTENCIES_WEBHOOK_URL,
        )
    ]


def test_inconsistencies_with_slack_webhook(caplog, settings, mocker):
    inconsistent_profile = JobSeekerProfileFactory(user=EmployerFactory())

    slack_mock = mocker.patch("itou.utils.management.commands.check_inconsistencies.send_slack_message")
    settings.SLACK_INCONSISTENCIES_WEBHOOK_URL = "http://slack.fake"
    call_command("check_inconsistencies")

    assert slack_mock.mock_calls == [
        mocker.call(
            text=(
                "1 incohérence trouvée:\n"
                f" - http://localhost:8000/admin/users/jobseekerprofile/{inconsistent_profile.pk}/change/ :"
                " ['Profil lié à un utilisateur non-candidat']"
            ),
            url=settings.SLACK_INCONSISTENCIES_WEBHOOK_URL,
        )
    ]


def test_limit_choices_to_inconsistency_detection(caplog, settings, mocker):
    diag = GEIQEligibilityDiagnosisFactory(from_employer=True)
    diag._meta.model.objects.filter(pk=diag.pk).update(author_geiq=CompanyFactory())
    slack_mock = mocker.patch("itou.utils.management.commands.check_inconsistencies.send_slack_message")
    settings.SLACK_INCONSISTENCIES_WEBHOOK_URL = "http://slack.fake"
    call_command("check_inconsistencies")

    assert "GEIQEligibilityDiagnosis - found 1 limit_choices_to inconsistencies" in caplog.text
    assert slack_mock.mock_calls == [
        mocker.call(
            text=(
                "1 incohérence trouvée:\n"
                f" - http://localhost:8000/admin/eligibility/geiqeligibilitydiagnosis/{diag.pk}/change/ :"
                " [\"La valeur du champ 'author_geiq' (GEIQ de l'auteur) ne respecte pas {'kind': CompanyKind.GEIQ}\"]"
            ),
            url=settings.SLACK_INCONSISTENCIES_WEBHOOK_URL,
        )
    ]
