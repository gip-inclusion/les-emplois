from django.test import TestCase

from itou.job_applications.enums import RefusalReason
from itou.job_applications.factories import JobApplicationFactory
from itou.metabase.management.commands import _job_applications


class MetabaseJobApplicationTest(TestCase):
    def get_fn_by_name(self, name):
        columns = _job_applications.TABLE_COLUMNS
        matching_columns = [c for c in columns if c["name"] == name]
        self.assertEqual(len(matching_columns), 1)
        fn = matching_columns[0]["fn"]
        return fn

    def test_refusal_reason_old_value(self):
        fn = self.get_fn_by_name("motif_de_refus")
        ja = JobApplicationFactory(refusal_reason=RefusalReason.ELIGIBILITY_DOUBT.value)
        self.assertIn(ja.refusal_reason, RefusalReason.hidden())
        self.assertEqual(fn(ja), ja.refusal_reason.label)

    def test_refusal_reason_current_value(self):
        fn = self.get_fn_by_name("motif_de_refus")
        ja = JobApplicationFactory(refusal_reason=RefusalReason.DID_NOT_COME.value)
        self.assertNotIn(ja.refusal_reason, RefusalReason.hidden())
        self.assertEqual(fn(ja), ja.refusal_reason.label)

    def test_refusal_reason_empty_value(self):
        fn = self.get_fn_by_name("motif_de_refus")
        ja = JobApplicationFactory(refusal_reason="")
        self.assertEqual(fn(ja), None)
