import datetime

import pytest
from django.template import Context, Template
from freezegun import freeze_time

from itou.approvals.enums import Origin
from itou.asp.models import Commune
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory, SuspensionFactory
from tests.cities.factories import create_city_geispolsheim
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.utils.testing import get_request, pretty_indented


public_id = "997a1eaf-6fad-4256-b371-31bb05c94862"
approval_number = "XXXXX1234567"


@freeze_time("2024-08-06")
def test_expired_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    request = get_request(approval.eligibility_diagnosis.author)  # an authorized prescriber linked to the job seeker
    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval version='box' request=request %}"
    )
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_future_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2025, 1, 1), number=approval_number, public_id=public_id)
    request = get_request(approval.eligibility_diagnosis.author)  # an authorized prescriber linked to the job seeker
    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval version='box' request=request %}"
    )
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    request = get_request(approval.eligibility_diagnosis.author)  # an authorized prescriber linked to the job seeker
    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval version='box' request=request %}"
    )
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval_with_pending_prolongation_request(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    ProlongationRequestFactory(approval=approval, start_at=approval.end_at)
    request = get_request(approval.eligibility_diagnosis.author)  # an authorized prescriber linked to the job seeker
    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval version='box' request=request %}"
    )
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_suspended_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    SuspensionFactory(
        approval=approval,
        start_at=datetime.date(2024, 8, 1),
        end_at=datetime.date(2024, 8, 31),
    )
    request = get_request(approval.eligibility_diagnosis.author)  # an authorized prescriber linked to the job seeker
    template = Template(
        "{% load approvals %}{% approval_details_box approval=approval version='box' request=request %}"
    )
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_box_without_link(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    template = Template("{% load approvals %}{% approval_details_box approval=approval version='box_without_link' %}")
    assert pretty_indented(template.render(Context({"approval": approval}))) == snapshot


@freeze_time("2024-08-06")
@pytest.mark.parametrize("origin", [Origin.DEFAULT, Origin.PE_APPROVAL])
def test_details_view_version(snapshot, origin):
    approval = ApprovalFactory(
        start_at=datetime.date(2024, 1, 1),
        number=approval_number,
        public_id=public_id,
        origin_pe_approval=origin == Origin.PE_APPROVAL,
    )
    template = Template("{% load approvals %}{% approval_details_box approval=approval version='details_view' %}")
    assert pretty_indented(template.render(Context({"approval": approval}))) == snapshot


@freeze_time("2024-08-06")
def test_job_seeker_dashboard_expired_approval_in_waiting_period_with_valid_diagnosis(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    IAEEligibilityDiagnosisFactory(job_seeker=approval.user, from_prescriber=True)
    request = get_request(approval.user)
    template = Template(
        "{% load approvals %}"
        "{% approval_details_box approval=approval version='job_seeker_dashboard' request=request %}"
    )
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot(
        name="without city"
    )
    approval.user.jobseeker_profile.hexa_commune = Commune.objects.by_insee_code("67152")
    approval.user.jobseeker_profile.save(update_fields=("hexa_commune",))
    approval.user.jobseeker_profile.hexa_commune.city = create_city_geispolsheim()
    approval.user.jobseeker_profile.hexa_commune.save(update_fields=("city",))

    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot(
        name="with city"
    )


@freeze_time("2024-08-06")
def test_job_seeker_dashboard_expired_approval_in_waiting_period_without_diagnosis(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    request = get_request(approval.user)

    template = Template(
        "{% load approvals %}"
        "{% approval_details_box approval=approval version='job_seeker_dashboard' request=request %}"
    )
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot(
        name="without_city"
    )
    approval.user.jobseeker_profile.hexa_commune = Commune.objects.by_insee_code("67152")
    approval.user.jobseeker_profile.save(update_fields=("hexa_commune",))
    approval.user.jobseeker_profile.hexa_commune.city = create_city_geispolsheim()
    approval.user.jobseeker_profile.hexa_commune.save(update_fields=("city",))
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot(
        name="with_city"
    )
