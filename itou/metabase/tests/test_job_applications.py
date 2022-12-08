from itou.job_applications.enums import RefusalReason
from itou.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    JobApplicationSentByPrescriberPoleEmploiFactory,
)
from itou.metabase.management.commands._job_applications import TABLE
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils.test import TestCase


class MetabaseJobApplicationTest(TestCase):
    def test_refusal_reason_old_value(self):
        ja = JobApplicationFactory(refusal_reason=RefusalReason.ELIGIBILITY_DOUBT.value)
        self.assertIn(ja.refusal_reason, RefusalReason.hidden())
        self.assertEqual(TABLE.get(column_name="motif_de_refus", input=ja), ja.get_refusal_reason_display())

    def test_refusal_reason_current_value(self):
        ja = JobApplicationFactory(refusal_reason=RefusalReason.DID_NOT_COME.value)
        self.assertNotIn(ja.refusal_reason, RefusalReason.hidden())
        self.assertEqual(TABLE.get(column_name="motif_de_refus", input=ja), ja.get_refusal_reason_display())

    def test_refusal_reason_empty_value(self):
        ja = JobApplicationFactory(refusal_reason="")
        self.assertEqual(TABLE.get(column_name="motif_de_refus", input=ja), None)

    def test_ja_sent_by_pe(self):
        ja = JobApplicationSentByPrescriberPoleEmploiFactory()
        self.assertEqual(
            TABLE.get(column_name="nom_prénom_conseiller", input=ja),
            f"{ja.sender.last_name.upper()} {ja.sender.first_name}",
        )
        self.assertEqual(
            TABLE.get(column_name="safir_org_prescripteur", input=ja),
            ja.sender_prescriber_organization.code_safir_pole_emploi,
        )
        self.assertEqual(len(ja.sender_prescriber_organization.code_safir_pole_emploi), 5)

    def test_ja_sent_by_spip(self):
        ja = JobApplicationSentByPrescriberOrganizationFactory(
            sender_prescriber_organization__kind=PrescriberOrganizationKind.SPIP
        )
        self.assertEqual(
            TABLE.get(column_name="nom_prénom_conseiller", input=ja),
            f"{ja.sender.last_name.upper()} {ja.sender.first_name}",
        )
        self.assertEqual(TABLE.get(column_name="safir_org_prescripteur", input=ja), None)

    def test_ja_sent_by_exotic_prescriber_organization(self):
        ja = JobApplicationSentByPrescriberOrganizationFactory(
            sender_prescriber_organization__kind=PrescriberOrganizationKind.CHRS
        )
        self.assertNotEqual(ja.sender_prescriber_organization.kind, PrescriberOrganizationKind.PE)
        self.assertEqual(TABLE.get(column_name="nom_prénom_conseiller", input=ja), None)
        self.assertEqual(TABLE.get(column_name="safir_org_prescripteur", input=ja), None)
