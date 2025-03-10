from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.core.management import call_command
from django.utils import timezone

from itou.job_applications.enums import (
    AUTO_REJECT_JOB_APPLICATION_DELAY,
    AUTO_REJECT_JOB_APPLICATION_STATES,
    JobApplicationState,
)
from itou.job_applications.models import JobApplication
from tests.job_applications.factories import JobApplicationFactory


auto_answer = (
    "Votre candidature a été automatiquement déclinée car elle n’a pas reçu de réponse depuis plus de 2 mois.\n"
    "\n"
    "Si vous êtes toujours en recherche d’emploi, nous vous invitons à poursuivre vos démarches. Pour maximiser vos "
    "chances de retour à l’emploi, n’hésitez pas à vous faire accompagner par un prescripteur habilité (France Travail"
    ", Mission Locale, Cap emploi, Service social du Conseil départemental…).\n"
    "\n"
    "Pour trouver les prescripteurs habilités présents sur votre territoire, consultez notre moteur de recherche : https://emplois.inclusion.beta.gouv.fr/search/prescribers/results\n"
    "\n"
    "Nous vous souhaitons une pleine réussite dans vos démarches.\n"
    "\n"
    "L’Equipe des Emplois de l’inclusion\n"
)


@pytest.mark.parametrize("state", AUTO_REJECT_JOB_APPLICATION_STATES)
def test_reject_job_applications_after_delay(state, mailoutbox):
    JobApplicationFactory(
        state=state, updated_at=timezone.now() - relativedelta(days=AUTO_REJECT_JOB_APPLICATION_DELAY)
    )
    call_command("reject_job_applications_after_delay")
    job_application = JobApplication.objects.get()
    assert job_application.state == JobApplicationState.REFUSED
    assert job_application.refusal_reason == "auto"
    assert job_application.refusal_reason_shared_with_job_seeker
    assert job_application.answer == auto_answer


@mock.patch(
    "itou.job_applications.management.commands.reject_job_applications_after_delay.open", mock.mock_open(read_data="")
)
def test_message_file_is_missing():
    with pytest.raises(Exception, match="Auto refusal message is empty."):
        call_command("reject_job_applications_after_delay")
