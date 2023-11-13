import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone

from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplicationWorkflow
from itou.users.enums import UserKind
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByCompanyFactory,
    JobApplicationSentByPrescriberFactory,
)
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


class JobApplicationTransferModelTest(TestCase):
    def test_is_in_transferable_state(self):
        # If job application is in ACCEPTED state
        # it can't be transfered
        evil_states = [JobApplicationWorkflow.STATE_ACCEPTED]
        good_states = [
            JobApplicationWorkflow.STATE_NEW,
            JobApplicationWorkflow.STATE_PROCESSING,
            JobApplicationWorkflow.STATE_POSTPONED,
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_CANCELLED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]

        for evil_state in evil_states:
            with self.subTest(evil_state):
                job_application = JobApplicationFactory(state=evil_state)
                assert not job_application.is_in_transferable_state

        for good_state in good_states:
            with self.subTest(good_state):
                job_application = JobApplicationFactory(state=good_state)
                assert job_application.is_in_transferable_state

    def test_can_be_transferred(self):
        # Only users in both origin and target SIAE
        # can transfer a job_application
        # (provided it is in correct state)
        origin_company = CompanyFactory(with_membership=True)
        target_company = CompanyFactory(with_membership=True)

        origin_user = origin_company.members.first()
        target_user = target_company.members.first()
        lambda_user = JobSeekerFactory()
        target_company.members.add(origin_user)

        job_application = JobApplicationFactory(to_company=origin_company, state=JobApplicationWorkflow.STATE_ACCEPTED)

        assert origin_user.kind == UserKind.EMPLOYER
        assert target_user.kind == UserKind.EMPLOYER
        assert not job_application.can_be_transferred(target_user, job_application.to_company)
        assert not job_application.can_be_transferred(lambda_user, target_company)
        assert not job_application.can_be_transferred(target_user, target_company)
        assert not job_application.can_be_transferred(origin_user, target_company)

        job_application.state = JobApplicationWorkflow.STATE_PROCESSING

        assert job_application.can_be_transferred(origin_user, target_company)

    def test_transfer_to(self):
        # If all conditions are valid, a user can transfer job applications between SIAE they are member of,
        # provided job application is in an acceptable state.
        # After transfer:
        # - job application is not linked to origin SIAE anymore (only to target SIAE)
        # - eligibility diagnosis is deleted if not created by an authorized prescriber
        origin_company = CompanyFactory(with_membership=True)
        target_company = CompanyFactory(with_membership=True)

        origin_user = origin_company.members.first()
        target_user = target_company.members.first()
        lambda_user = JobSeekerFactory()
        target_company.members.add(origin_user)

        job_application = JobApplicationFactory(
            to_company=origin_company,
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
        )

        # Conditions hould be covered by previous test, but does not hurt (and tests raise)
        with pytest.raises(ValidationError):
            job_application.transfer_to(lambda_user, target_company)
        with pytest.raises(ValidationError):
            job_application.transfer_to(origin_user, origin_company)
        with pytest.raises(ValidationError):
            job_application.transfer_to(target_user, target_company)
        with pytest.raises(ValidationError):
            job_application.transfer_to(origin_user, target_company)

        job_application.state = JobApplicationWorkflow.STATE_PROCESSING
        job_application.transfer_to(origin_user, target_company)
        job_application.refresh_from_db()

        # "Normal" transfer
        assert job_application.to_company == target_company
        assert job_application.state == JobApplicationWorkflow.STATE_NEW
        assert job_application.eligibility_diagnosis is not None

        # Eligibilty diagnosis not sent by authorized prescriber must be deleted
        job_application = JobApplicationSentByCompanyFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_company=origin_company,
            eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory(),
        )
        eligibility_diagnosis_pk = job_application.eligibility_diagnosis.pk
        job_application.transfer_to(origin_user, target_company)
        job_application.refresh_from_db()

        assert job_application.to_company == target_company
        assert job_application.state == JobApplicationWorkflow.STATE_NEW
        assert job_application.eligibility_diagnosis is None
        assert not EligibilityDiagnosis.objects.filter(pk=eligibility_diagnosis_pk)

    def test_transfer_to_without_sender(self):
        origin_company = CompanyFactory(with_membership=True)
        target_company = CompanyFactory(with_membership=True)
        origin_user = origin_company.members.first()
        target_company.members.first()
        target_company.members.add(origin_user)

        job_application = JobApplicationFactory(
            to_company=origin_company,
            sent_by_authorized_prescriber_organisation=True,
            state=JobApplicationWorkflow.STATE_PROCESSING,
        )
        # Sender user account is deleted.
        job_application.sender = None
        job_application.save(update_fields=["sender"])

        job_application.transfer_to(origin_user, target_company)
        job_application.refresh_from_db()

        assert job_application.to_company == target_company
        assert job_application.state == JobApplicationWorkflow.STATE_NEW

    def test_model_fields(self):
        # Check new fields in model
        origin_company = CompanyFactory(with_membership=True)
        target_company = CompanyFactory(with_membership=True)

        origin_user = origin_company.members.first()
        target_user = target_company.members.first()
        target_company.members.add(origin_user)

        job_application = JobApplicationSentByCompanyFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_company=origin_company,
            eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory(),
            answer="Answer to job seeker",
            answer_to_prescriber="Answer to prescriber",
        )

        # Failing to transfer must not update new fields
        with pytest.raises(ValidationError):
            job_application.transfer_to(target_user, target_company)
        assert job_application.transferred_by is None
        assert job_application.transferred_from is None
        assert job_application.transferred_at is None

        with self.assertNumQueries(
            2  # Check user is in both origin and dest siae
            + 6  # Caused by `full_clean()` : `clean_fields()`
            + 3  # Integrity constraints check (full clean)
            + 1  # Update job application
            + 1  # Check if approvals are linked to diagnosis because of on_delete=set_null
            + 1  # Check if job applications are linked because of on_delete=set_null
            + 2  # Delete diagnosis and criteria made by the SIAE
            + 1  # Select user for email
        ):
            job_application.transfer_to(origin_user, target_company)

        job_application.refresh_from_db()

        assert job_application.transferred_by == origin_user
        assert job_application.transferred_from == origin_company
        assert timezone.localdate() == job_application.transferred_at.date()
        assert job_application.to_company == target_company
        assert job_application.state == JobApplicationWorkflow.STATE_NEW
        assert job_application.eligibility_diagnosis is None
        assert job_application.answer == ""
        assert job_application.answer_to_prescriber == ""

    def test_workflow_transitions(self):
        # `source` contains possible entry points of transition
        for from_state in JobApplicationWorkflow.transitions["transfer"].source:
            with self.subTest(from_state):
                job_application = JobApplicationSentByCompanyFactory(state=from_state)
                job_application.state = JobApplicationWorkflow.STATE_NEW
                job_application.save()  # Triggers transition check

    def test_transfer_must_notify_siae_and_job_seeker(self):
        # Send email notification of transfer to :
        # - origin SIAE
        # - job seeker
        # - Prescriber (if any linked eligibility diagnosis was not sent by a SIAE)
        origin_company = CompanyFactory(with_membership=True)
        target_company = CompanyFactory(with_membership=True)

        origin_user = origin_company.members.first()
        target_company.members.add(origin_user)

        job_application = JobApplicationSentByCompanyFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_company=origin_company,
            eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory(),
        )
        job_seeker = job_application.job_seeker

        job_application.transfer_to(origin_user, target_company)

        # Eligigibility diagnosis is done by SIAE : must not send an email
        assert len(mail.outbox) == 2

        assert len(mail.outbox[0].to) == 1
        assert origin_user.email in mail.outbox[0].to
        assert f"La candidature de {job_seeker.get_full_name()} a été transférée" == mail.outbox[0].subject
        assert "a transféré la candidature de :" in mail.outbox[0].body

        assert len(mail.outbox[1].to) == 1
        assert job_application.job_seeker.email in mail.outbox[1].to
        assert "Votre candidature a été transférée à une autre structure" in mail.outbox[1].subject
        assert "a transféré votre candidature à la structure" in mail.outbox[1].body

    def test_transfer_must_notify_prescriber(self):
        # Same test and conditions as above, but this time prescriber
        # at the origin of the eligibility disgnosis must be notified
        origin_company = CompanyFactory(with_membership=True)
        target_company = CompanyFactory(with_membership=True)

        origin_user = origin_company.members.first()
        target_company.members.add(origin_user)

        # Eligibility diagnosis was made by a prescriber
        job_application = JobApplicationSentByPrescriberFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_company=origin_company,
            eligibility_diagnosis=EligibilityDiagnosisFactory(),
        )
        job_seeker = job_application.job_seeker

        job_application.transfer_to(origin_user, target_company)

        assert len(mail.outbox) == 3

        # Other email content have been checked in previous test
        # Focusing on prescriber email content
        assert len(mail.outbox[2].to) == 1
        assert job_application.sender.email in mail.outbox[2].to
        assert f"La candidature de {job_seeker.get_full_name()} a été transférée" == mail.outbox[2].subject
        assert "a transféré la candidature de :" in mail.outbox[2].body

    def test_transfer_notifications_to_many_employers(self):
        # Same as test_transfer_must_notify_siae_and_job_seeker
        # but with to recipients for SIAE transfer notification
        origin_company = CompanyWith2MembershipsFactory()
        target_company = CompanyFactory(with_membership=True)

        origin_user_1 = origin_company.members.all()[0]
        origin_user_2 = origin_company.members.all()[1]
        target_company.members.add(origin_user_1)

        job_application = JobApplicationSentByCompanyFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            to_company=origin_company,
            eligibility_diagnosis=EligibilityDiagnosisMadeBySiaeFactory(),
        )
        job_seeker = job_application.job_seeker

        job_application.transfer_to(origin_user_1, target_company)

        # Only checking SIAE email
        assert len(mail.outbox) == 2
        assert len(mail.outbox[0].to) == 2
        assert origin_user_1.email in mail.outbox[0].to
        assert origin_user_2.email in mail.outbox[0].to
        assert f"La candidature de {job_seeker.get_full_name()} a été transférée" == mail.outbox[0].subject
        assert "a transféré la candidature de :" in mail.outbox[0].body
