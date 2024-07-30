from itou.job_applications.enums import RefusalReason
from itou.metabase.tables.job_applications import TABLE
from itou.prescribers.enums import PrescriberOrganizationKind
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    JobApplicationSentByPrescriberPoleEmploiFactory,
)


def test_refusal_reason_old_value():
    ja = JobApplicationFactory(refusal_reason=RefusalReason.ELIGIBILITY_DOUBT.value)
    assert ja.refusal_reason in RefusalReason.hidden()
    assert TABLE.get(column_name="motif_de_refus", input=ja) == str(ja.refusal_reason)


def test_refusal_reason_current_value():
    ja = JobApplicationFactory(refusal_reason=RefusalReason.DID_NOT_COME.value)
    assert ja.refusal_reason not in RefusalReason.hidden()
    assert TABLE.get(column_name="motif_de_refus", input=ja) == str(ja.refusal_reason)


def test_refusal_reason_empty_value():
    ja = JobApplicationFactory(refusal_reason="")
    assert TABLE.get(column_name="motif_de_refus", input=ja) is None


def test_ja_sent_by_pe():
    ja = JobApplicationSentByPrescriberPoleEmploiFactory()
    assert (
        TABLE.get(column_name="nom_prénom_conseiller", input=ja)
        == f"{ja.sender.last_name.upper()} {ja.sender.first_name}"
    )
    assert (
        TABLE.get(column_name="safir_org_prescripteur", input=ja)
        == ja.sender_prescriber_organization.code_safir_pole_emploi
    )
    assert len(ja.sender_prescriber_organization.code_safir_pole_emploi) == 5


def test_ja_sent_by_spip():
    ja = JobApplicationSentByPrescriberOrganizationFactory(
        sender_prescriber_organization__kind=PrescriberOrganizationKind.SPIP
    )
    assert (
        TABLE.get(column_name="nom_prénom_conseiller", input=ja)
        == f"{ja.sender.last_name.upper()} {ja.sender.first_name}"
    )
    assert TABLE.get(column_name="safir_org_prescripteur", input=ja) is None


def test_ja_sent_by_exotic_prescriber_organization():
    ja = JobApplicationSentByPrescriberOrganizationFactory(
        sender_prescriber_organization__kind=PrescriberOrganizationKind.CHRS
    )
    assert ja.sender_prescriber_organization.kind != PrescriberOrganizationKind.PE
    assert TABLE.get(column_name="nom_prénom_conseiller", input=ja) is None
    assert TABLE.get(column_name="safir_org_prescripteur", input=ja) is None
