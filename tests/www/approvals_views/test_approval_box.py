import datetime

from django.template import Context
from freezegun import freeze_time

from itou.asp.models import Commune
from tests.approvals.factories import (
    ApprovalFactory,
    PoleEmploiApprovalFactory,
    ProlongationRequestFactory,
    SuspensionFactory,
)
from tests.cities.factories import create_city_geispolsheim
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.utils.test import load_template


public_id = "997a1eaf-6fad-4256-b371-31bb05c94862"
approval_number = "XXXXX1234567"


@freeze_time("2024-08-06")
def test_expired_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval, "link_from_current_url": "/"})) == snapshot


@freeze_time("2024-08-06")
def test_future_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2025, 1, 1), number=approval_number, public_id=public_id)

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval, "link_from_current_url": "/"})) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval, "link_from_current_url": ""})) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval_with_pending_prolongation_request(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    ProlongationRequestFactory(approval=approval, start_at=approval.end_at)

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval, "link_from_current_url": "/"})) == snapshot


@freeze_time("2024-08-06")
def test_suspended_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    SuspensionFactory(
        approval=approval,
        start_at=datetime.date(2024, 8, 1),
        end_at=datetime.date(2024, 8, 31),
    )

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval, "link_from_current_url": "/"})) == snapshot


@freeze_time("2024-08-06")
def test_expired_pe_approval(snapshot):
    pe_approval = PoleEmploiApprovalFactory(start_at=datetime.date(2022, 1, 1), number="123456789012")

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": pe_approval})) == snapshot


@freeze_time("2024-08-06")
def test_valid_pe_approval(snapshot):
    # One of the last 8 valid Pole Emploi
    pe_approval = PoleEmploiApprovalFactory(start_at=datetime.date(2024, 1, 1), number="123456789012")

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": pe_approval})) == snapshot


@freeze_time("2024-08-06")
def test_expired_approval_in_waiting_period_with_valid_diagnosis(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    IAEEligibilityDiagnosisFactory(job_seeker=approval.user, from_prescriber=True)

    template = load_template("approvals/includes/box.html")
    assert template.render(
        Context(
            {
                "approval": approval,
                "link_from_current_url": "/",
                "job_seeker_dashboard_version": True,
            }
        )
    ) == snapshot(name="without city")
    approval.user.jobseeker_profile.hexa_commune = Commune.objects.by_insee_code("67152")
    approval.user.jobseeker_profile.save(update_fields=("hexa_commune",))
    approval.user.jobseeker_profile.hexa_commune.city = create_city_geispolsheim()
    approval.user.jobseeker_profile.hexa_commune.save(update_fields=("city",))

    assert template.render(
        Context(
            {
                "approval": approval,
                "link_from_current_url": "/",
                "job_seeker_dashboard_version": True,
            }
        )
    ) == snapshot(name="with city")


@freeze_time("2024-08-06")
def test_expired_approval_in_waiting_period_without_diagnosis(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)

    template = load_template("approvals/includes/box.html")
    assert template.render(
        Context(
            {
                "approval": approval,
                "link_from_current_url": "/",
                "job_seeker_dashboard_version": True,
            }
        )
    ) == snapshot(name="without_city")
    approval.user.jobseeker_profile.hexa_commune = Commune.objects.by_insee_code("67152")
    approval.user.jobseeker_profile.save(update_fields=("hexa_commune",))
    approval.user.jobseeker_profile.hexa_commune.city = create_city_geispolsheim()
    approval.user.jobseeker_profile.hexa_commune.save(update_fields=("city",))
    assert template.render(
        Context(
            {
                "approval": approval,
                "link_from_current_url": "/",
                "job_seeker_dashboard_version": True,
            }
        )
    ) == snapshot(name="with_city")
