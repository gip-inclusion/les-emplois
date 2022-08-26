from django.test import TestCase

from itou.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from itou.job_applications.factories import JobApplicationSentBySiaeFactory, JobApplicationWithApprovalFactory
from itou.metabase.management.commands._job_seekers import TABLE


class MetabaseJobSeekerTest(TestCase):
    def test_job_seeker_with_diagnostic_from_prescriber(self):
        ja = JobApplicationWithApprovalFactory()
        js = ja.job_seeker
        diagnosis = EligibilityDiagnosisFactory(job_seeker=js)
        self.assertEqual(
            TABLE.get(column_name="id_auteur_diagnostic_prescripteur", input=js),
            diagnosis.author_prescriber_organization.id,
        )
        self.assertEqual(TABLE.get(column_name="id_auteur_diagnostic_employeur", input=js), None)

    def test_job_seeker_with_diagnostic_from_employer(self):
        ja = JobApplicationSentBySiaeFactory()
        js = ja.job_seeker
        to_siae_staff_member = ja.to_siae.members.first()
        diagnosis = EligibilityDiagnosisMadeBySiaeFactory(
            job_seeker=js, author=to_siae_staff_member, author_siae=ja.to_siae
        )
        self.assertEqual(TABLE.get(column_name="id_auteur_diagnostic_prescripteur", input=js), None)
        self.assertEqual(TABLE.get(column_name="id_auteur_diagnostic_employeur", input=js), diagnosis.author_siae.id)
