from django.test import TestCase

from itou.metabase.management.commands import _job_seekers
from itou.metabase.tests._utils import get_fn_by_name


def get_result(name, value):
    return get_fn_by_name(name, module=_job_seekers)(value)


class MetabaseJobSeekerTest(TestCase):
    def test_job_seeker_with_diagnostic_from_prescriber(self):
        pass
