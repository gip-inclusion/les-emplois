import datetime

from django.contrib.sessions.middleware import SessionMiddleware
from django.template import Context, Template
from django.test import RequestFactory
from django.urls import reverse
from freezegun import freeze_time

from itou.asp.models import Commune
from itou.utils.perms.middleware import ItouCurrentOrganizationMiddleware
from tests.approvals.factories import (
    ApprovalFactory,
    PoleEmploiApprovalFactory,
    ProlongationRequestFactory,
    SuspensionFactory,
)
from tests.cities.factories import create_city_geispolsheim
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory
from tests.utils.test import pretty_indented
from tests.utils.tests import get_response_for_middlewaremixin


public_id = "997a1eaf-6fad-4256-b371-31bb05c94862"
approval_number = "XXXXX1234567"


def get_request(user):
    factory = RequestFactory()
    request = factory.get("/")
    request.user = user
    SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
    ItouCurrentOrganizationMiddleware(get_response_for_middlewaremixin)(request)
    return request


@freeze_time("2024-08-06")
def test_expired_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    request = get_request(PrescriberMembershipFactory(organization__authorized=True).user)
    approval.user.created_by = request.user  # link the prescriber to the job seeker
    approval.user.save()
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_future_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2025, 1, 1), number=approval_number, public_id=public_id)
    request = get_request(PrescriberMembershipFactory(organization__authorized=True).user)
    approval.user.created_by = request.user  # link the prescriber to the job seeker
    approval.user.save()
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    request = get_request(PrescriberMembershipFactory(organization__authorized=True).user)
    approval.user.created_by = request.user  # link the prescriber to the job seeker
    approval.user.save()
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval_with_pending_prolongation_request(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number=approval_number, public_id=public_id)
    ProlongationRequestFactory(approval=approval, start_at=approval.end_at)
    request = get_request(PrescriberMembershipFactory(organization__authorized=True).user)
    approval.user.created_by = request.user  # link the prescriber to the job seeker
    approval.user.save()
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
    request = get_request(PrescriberMembershipFactory(organization__authorized=True).user)
    approval.user.created_by = request.user  # link the prescriber to the job seeker
    approval.user.save()
    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")
    assert pretty_indented(template.render(Context({"approval": approval, "request": request}))) == snapshot


@freeze_time("2024-08-06")
def test_expired_pe_approval(snapshot):
    pe_approval = PoleEmploiApprovalFactory(start_at=datetime.date(2022, 1, 1), number="123456789012")
    template = Template("{% load approvals %}{% approval_details_box approval=approval %}")
    assert pretty_indented(template.render(Context({"approval": pe_approval}))) == snapshot


@freeze_time("2024-08-06")
def test_valid_pe_approval(snapshot):
    # One of the last 8 valid Pole Emploi
    pe_approval = PoleEmploiApprovalFactory(start_at=datetime.date(2024, 1, 1), number="123456789012")
    template = Template("{% load approvals %}{% approval_details_box approval=approval %}")
    assert pretty_indented(template.render(Context({"approval": pe_approval}))) == snapshot


@freeze_time("2024-08-06")
def test_expired_approval_in_waiting_period_with_valid_diagnosis(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number=approval_number, public_id=public_id)
    IAEEligibilityDiagnosisFactory(job_seeker=approval.user, from_prescriber=True)
    request = get_request(approval.user)
    approval.user.created_by = request.user  # link the prescriber to the job seeker
    approval.user.save()

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
    request = get_request(approval.user)
    approval.user.created_by = request.user  # link the prescriber to the job seeker
    approval.user.save()

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


def test_approval_detail_link():
    approval = ApprovalFactory()

    approval_detail_url = reverse("approvals:details", kwargs={"public_id": approval.public_id})

    # No request
    template = Template("{% load approvals %}{% approval_details_box approval=approval %}")
    assert approval_detail_url not in template.render(Context({"approval": approval}))

    template = Template("{% load approvals %}{% approval_details_box approval=approval request=request %}")

    for user in [
        approval.user,
        JobApplicationFactory(
            job_seeker=approval.user, sent_by_authorized_prescriber_organisation=True
        ).sender,  # linked authorized prescriber
        JobApplicationFactory(job_seeker=approval.user).to_company.members.first(),  # employer whom received a job app
        JobApplicationFactory(job_seeker=approval.user, sent_by_company=True).sender,  # employer who sent a job app
    ]:
        request = get_request(user)
        assert approval_detail_url in template.render(Context({"approval": approval, "request": request}))

    for bad_user in [
        JobSeekerFactory(),  # another job seeker
        PrescriberMembershipFactory(organization__authorized=True).user,  # a random authorized prescriber
        JobApplicationFactory(job_seeker=approval.user).sender,  # linked non authorized prescriber
        EmployerFactory(with_company=True),  # a random employer
    ]:
        request = get_request(bad_user)
        assert approval_detail_url not in template.render(Context({"approval": approval, "request": request}))
