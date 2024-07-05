import datetime

import pytest  # noqa
from django.template import Context, Template
from freezegun import freeze_time

import itou.approvals.enums as approvals_enums
from tests.approvals.factories import ApprovalFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.users.factories import EmployerFactory, PrescriberFactory
from tests.utils.test import remove_static_hash


@freeze_time("2022-01-10")
class TestStatusInclude:
    def test_valid_approval_for_employer(self, snapshot, db):
        context = Context(
            {
                "common_approval": ApprovalFactory(for_snapshot=True),
                "user": EmployerFactory(),
                "hiring_pending": False,
                "job_application": None,
                "ApprovalOrigin": approvals_enums.Origin,
            }
        )
        rendered_template = Template('{% include "approvals/includes/status.html" %}').render(context)
        assert remove_static_hash(rendered_template) == snapshot(name="valid_approval_for_employer")

    def test_valid_approval_for_prescriber(self, snapshot, db):
        context = Context(
            {
                "common_approval": ApprovalFactory(for_snapshot=True),
                "user": PrescriberFactory(),
                "hiring_pending": False,
                "job_application": None,
                "ApprovalOrigin": approvals_enums.Origin,
            }
        )
        rendered_template = Template('{% include "approvals/includes/status.html" %}').render(context)
        assert remove_static_hash(rendered_template) == snapshot(name="valid_approval_for_prescriber")

    def test_expired_approval_without_eligibility_diagnosis_for_employer(self, snapshot, db):
        context = Context(
            {
                "common_approval": ApprovalFactory(for_snapshot=True, end_at=datetime.date(2022, 1, 1)),
                "user": EmployerFactory(),
                "hiring_pending": False,
                "job_application": None,
                "ApprovalOrigin": approvals_enums.Origin,
            }
        )
        rendered_template = Template('{% include "approvals/includes/status.html" %}').render(context)
        assert remove_static_hash(rendered_template) == snapshot(
            name="expired_approval_without_eligibility_diagnosis_for_employer"
        )

    def test_expired_approval_with_eligibility_diagnosis_for_employer(self, snapshot, db):
        approval = ApprovalFactory(for_snapshot=True, end_at=datetime.date(2022, 1, 1))
        approval.eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=approval.user)
        context = Context(
            {
                "common_approval": approval,
                "user": EmployerFactory(),
                "hiring_pending": False,
                "job_application": None,
                "ApprovalOrigin": approvals_enums.Origin,
            }
        )
        rendered_template = Template('{% include "approvals/includes/status.html" %}').render(context)
        assert remove_static_hash(rendered_template) == snapshot(
            name="expired_approval_with_eligibility_diagnosis_for_employer"
        )

    def test_expired_approval_with_eligibility_diagnosis_for_prescriber(self, snapshot, db):
        approval = ApprovalFactory(for_snapshot=True, end_at=datetime.date(2022, 1, 1))
        approval.eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=approval.user)
        context = Context(
            {
                "common_approval": approval,
                "user": PrescriberFactory(),
                "hiring_pending": False,
                "job_application": None,
                "ApprovalOrigin": approvals_enums.Origin,
            }
        )
        rendered_template = Template('{% include "approvals/includes/status.html" %}').render(context)
        assert remove_static_hash(rendered_template) == snapshot(
            name="expired_approval_with_eligibility_diagnosis_for_prescriber"
        )

    def test_expired_approval_with_eligibility_diagnosis_for_jobseeker(self, snapshot, db):
        approval = ApprovalFactory(for_snapshot=True, end_at=datetime.date(2022, 1, 1))
        approval.eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=approval.user)
        context = Context(
            {
                "common_approval": approval,
                "user": approval.user,
                "hiring_pending": False,
                "job_application": None,
                "ApprovalOrigin": approvals_enums.Origin,
            }
        )
        rendered_template = Template('{% include "approvals/includes/status.html" %}').render(context)
        assert remove_static_hash(rendered_template) == snapshot(
            name="expired_approval_with_eligibility_diagnosis_for_jobseeker"
        )

    def test_valid_approval_for_employer_not_from_pe_approval(self, snapshot, db):
        context = Context(
            {
                "common_approval": ApprovalFactory(
                    number="999999999999",
                    user__for_snapshot=True,
                    start_at=datetime.date(2000, 1, 1),
                    end_at=datetime.date(3000, 1, 1),
                    origin_ai_stock=True,
                ),
                "user": EmployerFactory(),
                "hiring_pending": False,
                "job_application": None,
                "ApprovalOrigin": approvals_enums.Origin,
            }
        )
        rendered_template = Template('{% include "approvals/includes/status.html" %}').render(context)
        assert remove_static_hash(rendered_template) == snapshot(name="valid_approval_for_employer")
