import io

from django.core import management

from itou.job_applications.factories import JobApplicationFactory
from itou.siae_evaluations.factories import EvaluatedSiaeFactory
from itou.siaes import factories as siaes_factories
from itou.siaes.enums import SiaeKind
from itou.utils.test import TestCase


class MoveSiaeDataTest(TestCase):
    def test_uses_wet_run(self):
        siae1 = siaes_factories.SiaeWithMembershipAndJobsFactory()
        siae2 = siaes_factories.SiaeFactory()
        management.call_command("move_siae_data", from_id=siae1.pk, to_id=siae2.pk)
        self.assertEqual(siae1.jobs.count(), 4)
        self.assertEqual(siae1.members.count(), 1)
        self.assertEqual(siae2.jobs.count(), 0)
        self.assertEqual(siae2.members.count(), 0)

        management.call_command("move_siae_data", from_id=siae1.pk, to_id=siae2.pk, wet_run=True)
        self.assertEqual(siae1.jobs.count(), 0)
        self.assertEqual(siae1.members.count(), 0)
        self.assertEqual(siae2.jobs.count(), 4)
        self.assertEqual(siae2.members.count(), 1)

    def test_does_not_stop_if_kind_is_different(self):
        siae1 = siaes_factories.SiaeWithMembershipAndJobsFactory(kind=SiaeKind.ACI)
        siae2 = siaes_factories.SiaeFactory(kind=SiaeKind.EATT)
        management.call_command("move_siae_data", from_id=siae1.pk, to_id=siae2.pk, wet_run=True)
        self.assertEqual(siae1.jobs.count(), 0)
        self.assertEqual(siae1.members.count(), 0)
        self.assertEqual(siae2.jobs.count(), 4)
        self.assertEqual(siae2.members.count(), 1)

    def test_evaluation_data_is_moved(self):
        stderr = io.StringIO()
        siae1 = siaes_factories.SiaeFactory()
        siae2 = siaes_factories.SiaeFactory()
        EvaluatedSiaeFactory(siae=siae1)
        management.call_command(
            "move_siae_data", from_id=siae1.pk, to_id=siae2.pk, stdout=io.StringIO(), stderr=stderr, wet_run=True
        )
        self.assertEqual(siae1.evaluated_siaes.count(), 0)
        self.assertEqual(siae2.evaluated_siaes.count(), 1)


def test_update_siaes_job_app_score():
    siae1 = siaes_factories.SiaeFactory()
    siae2 = JobApplicationFactory(to_siae__with_jobs=True).to_siae

    assert siae1.job_app_score is None
    assert siae2.job_app_score is None

    stdout = io.StringIO()
    management.call_command("update_siaes_job_app_score", stdout=stdout)
    # siae1 did not change (from None to None)
    assert "Updated 1 Siaes" in stdout.getvalue()

    siae1.refresh_from_db()
    siae2.refresh_from_db()

    assert siae1.job_app_score is None
    assert siae2.job_app_score is not None
