import io

from django.core import management
from django.test import TestCase

from itou.siae_evaluations.factories import EvaluatedSiaeFactory
from itou.siaes import factories as siaes_factories
from itou.siaes.enums import SiaeKind


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

    def test_stop_if_evaluation_in_place(self):
        stderr = io.StringIO()
        siae1 = siaes_factories.SiaeWithMembershipAndJobsFactory()
        siae2 = siaes_factories.SiaeFactory()
        EvaluatedSiaeFactory(siae=siae1)
        management.call_command(
            "move_siae_data", from_id=siae1.pk, to_id=siae2.pk, stdout=io.StringIO(), stderr=stderr
        )
        self.assertEqual(siae1.jobs.count(), 4)
        self.assertEqual(siae1.members.count(), 1)
        self.assertEqual(siae2.jobs.count(), 0)
        self.assertEqual(siae2.members.count(), 0)
        self.assertEqual(
            stderr.getvalue(),
            f"Moving the SIAE with id={siae1.pk} would cause inconsistencies with the DDETS evaluation campaigns !\n",
        )
