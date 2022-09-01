from django.test import TestCase

from itou.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from itou.job_applications.factories import JobApplicationSentBySiaeFactory, JobApplicationWithApprovalFactory
from itou.metabase.management.commands import _job_seekers
from itou.metabase.tests._utils import get_fn_by_name


def get_result(name, value):
    return get_fn_by_name(name, module=_job_seekers)(value)


class MetabaseJobSeekerTest(TestCase):
    def test_job_seeker_with_diagnostic_from_prescriber(self):
        ja = JobApplicationWithApprovalFactory()
        js = ja.job_seeker
        diagnosis = EligibilityDiagnosisFactory(job_seeker=js)
        self.assertEqual(
            get_result(name="id_auteur_diagnostic_prescripteur", value=js), diagnosis.author_prescriber_organization.id
        )
        self.assertEqual(get_result(name="id_auteur_diagnostic_employeur", value=js), None)

    def test_job_seeker_with_diagnostic_from_employer(self):
        ja = JobApplicationSentBySiaeFactory()
        js = ja.job_seeker
        to_siae_staff_member = ja.to_siae.members.first()
        diagnosis = EligibilityDiagnosisMadeBySiaeFactory(
            job_seeker=js, author=to_siae_staff_member, author_siae=ja.to_siae
        )
        self.assertEqual(get_result(name="id_auteur_diagnostic_prescripteur", value=js), None)
        self.assertEqual(get_result(name="id_auteur_diagnostic_employeur", value=js), diagnosis.author_siae.id)
