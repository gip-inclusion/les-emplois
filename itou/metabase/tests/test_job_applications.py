from django.test import TestCase

from itou.job_applications.enums import RefusalReason
from itou.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberOrganizationFactory
from itou.metabase.management.commands import _job_applications
from itou.metabase.tests._utils import get_fn_by_name
from itou.prescribers.enums import PrescriberOrganizationKind


def get_result(name, value):
    return get_fn_by_name(name, module=_job_applications)(value)


class MetabaseJobApplicationTest(TestCase):
    def test_refusal_reason_old_value(self):
        ja = JobApplicationFactory(refusal_reason=RefusalReason.ELIGIBILITY_DOUBT.value)
        self.assertIn(ja.refusal_reason, RefusalReason.hidden())
        self.assertEqual(get_result(name="motif_de_refus", value=ja), ja.get_refusal_reason_display())

    def test_refusal_reason_current_value(self):
        ja = JobApplicationFactory(refusal_reason=RefusalReason.DID_NOT_COME.value)
        self.assertNotIn(ja.refusal_reason, RefusalReason.hidden())
        self.assertEqual(get_result(name="motif_de_refus", value=ja), ja.get_refusal_reason_display())

    def test_refusal_reason_empty_value(self):
        ja = JobApplicationFactory(refusal_reason="")
        self.assertEqual(get_result(name="motif_de_refus", value=ja), None)

    def test_ja_sent_by_pe(self):
        ja = JobApplicationSentByPrescriberOrganizationFactory(sent_by_pole_emploi=True)
        self.assertEqual(
            get_result(name="nom_prénom_conseiller_pe", value=ja),
            f"{ja.sender.last_name.upper()} {ja.sender.first_name}",
        )
        self.assertEqual(
            get_result(name="safir_org_prescripteur", value=ja),
            ja.sender_prescriber_organization.code_safir_pole_emploi,
        )
        self.assertEqual(len(ja.sender_prescriber_organization.code_safir_pole_emploi), 5)

    def test_ja_sent_by_non_pe_prescriber_organization(self):
        ja = JobApplicationSentByPrescriberOrganizationFactory(
            sender_prescriber_organization__kind=PrescriberOrganizationKind.CHRS
        )
        self.assertNotEqual(ja.sender_prescriber_organization.kind, PrescriberOrganizationKind.PE)
        self.assertEqual(get_result(name="nom_prénom_conseiller_pe", value=ja), None)
        self.assertEqual(get_result(name="safir_org_prescripteur", value=ja), None)
