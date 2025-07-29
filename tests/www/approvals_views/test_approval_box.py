import datetime

from django.template import Context, Template
from django.test import RequestFactory
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
from tests.utils.testing import pretty_indented


public_id = "997a1eaf-6fad-4256-b371-31bb05c94862"
approval_number = "XXXXX1234567"


@freeze_time("2024-08-06")
def test_expired_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    request = RequestFactory().get("/")
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_future_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2025, 1, 1), number=approval_number, public_id=public_id)
    request = RequestFactory().get("/")
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    request = RequestFactory().get("/")
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_approval_no_details_link(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    request = RequestFactory().get("/")
    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval request=request hide_details_link=True %}"
    )
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval_with_pending_prolongation_request(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    ProlongationRequestFactory(approval=approval, start_at=approval.end_at)
    request = RequestFactory().get("/")
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_suspended_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    SuspensionFactory(
        approval=approval,
        start_at=datetime.date(2024, 8, 1),
        end_at=datetime.date(2024, 8, 31),
    )
    request = RequestFactory().get("/")
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_expired_pe_approval(snapshot):
    pe_approval = PoleEmploiApprovalFactory(start_at=datetime.date(2022, 1, 1), number="123456789012")
    request = RequestFactory().get("/")
    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval request=request hide_details_link=True %}"
    )
    assert pretty_indented(template.render(Context({"approval": pe_approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_valid_pe_approval(snapshot):
    # One of the last 8 valid Pole Emploi
    pe_approval = PoleEmploiApprovalFactory(start_at=datetime.date(2024, 1, 1), number="123456789012")
    request = RequestFactory().get("/")
    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval request=request hide_details_link=True %}"
    )
    assert pretty_indented(template.render(Context({"approval": pe_approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_expired_approval_in_waiting_period_with_valid_diagnosis(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    IAEEligibilityDiagnosisFactory(job_seeker=approval.user, from_prescriber=True)
    request = RequestFactory().get("/")

    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval request=request version=version %}"
    )
    assert pretty_indented(
        template.render(
            Context(
                {
                    "approval": approval,
                    "request": request,
                    "version": "job_seeker_dashboard",
                }
            )
        )
    ) == snapshot(name="without city")
    approval.user.jobseeker_profile.hexa_commune = Commune.objects.by_insee_code("67152")
    approval.user.jobseeker_profile.save(update_fields=("hexa_commune",))
    approval.user.jobseeker_profile.hexa_commune.city = create_city_geispolsheim()
    approval.user.jobseeker_profile.hexa_commune.save(update_fields=("city",))

    assert pretty_indented(
        template.render(
            Context(
                {
                    "approval": approval,
                    "request": request,
                    "version": "job_seeker_dashboard",
                }
            )
        )
    ) == snapshot(name="with city")


@freeze_time("2024-08-06")
def test_expired_approval_in_waiting_period_without_diagnosis(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    request = RequestFactory().get("/")

    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval request=request version=version %}"
    )
    assert pretty_indented(
        template.render(
            Context(
                {
                    "approval": approval,
                    "request": request,
                    "version": "job_seeker_dashboard",
                }
            )
        )
    ) == snapshot(name="without_city")
    approval.user.jobseeker_profile.hexa_commune = Commune.objects.by_insee_code("67152")
    approval.user.jobseeker_profile.save(update_fields=("hexa_commune",))
    approval.user.jobseeker_profile.hexa_commune.city = create_city_geispolsheim()
    approval.user.jobseeker_profile.hexa_commune.save(update_fields=("city",))
    assert pretty_indented(
        template.render(
            Context(
                {
                    "approval": approval,
                    "request": request,
                    "version": "job_seeker_dashboard",
                }
            )
        )
    ) == snapshot(name="with_city")
