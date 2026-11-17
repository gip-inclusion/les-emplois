"""The acts an advisor did for a job seeker, rebuilt from where the platform records them.

A JobSeekerAssignment keeps the kind and the date of the advisor's last act only. The earlier ones are found in the
job applications they sent, the hirings they validated, the eligibility diagnoses they made, the support reports
they filled, the orientations they sent and the job seeker account they created, for the assignment's organization.

Each source shows what the matching tab of the existing job seeker page shows, no more: the job applications and
orientations of the user's scope (and the external ones, without details, for authorized prescribers allowed to
see them), the IAE diagnoses to IAE actors, the GEIQ diagnoses to prescribers and GEIQ, the reports the user may read.
"""

import dataclasses
import datetime

from django.db.models import Exists, OuterRef, Q, Value
from django.urls import reverse
from django.utils import timezone

from itou.eligibility.enums import AuthorKind
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.insertion.models import Orientation
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog, JobApplicationWorkflow
from itou.job_applications.utils import xp_ref_iae_job_applications
from itou.users.enums import ActionKind
from itou.users.perms import can_view_pro_support_report
from itou.www.job_seekers_views.views import can_view_external_actions


@dataclasses.dataclass
class Act:
    kind: str
    at: datetime.datetime
    detail: str = ""
    # Where the act can be read, when the user may.
    url: str = ""

    @property
    def title(self):
        return ActionKind(self.kind).label[:1].upper() + ActionKind(self.kind).label[1:]

    @property
    def icon(self):
        return {
            ActionKind.CREATE: "ri-user-add-line",
            ActionKind.APPLY: "ri-draft-line",
            ActionKind.HIRE: "ri-briefcase-4-line",
            ActionKind.ACCEPT: "ri-briefcase-4-line",
            ActionKind.IAE_ELIGIBILITY: "ri-shield-check-line",
            ActionKind.GEIQ_ELIGIBILITY: "ri-shield-check-line",
            ActionKind.SELF_ASSIGN: "ri-user-follow-line",
            ActionKind.ORIENT: "ri-signpost-line",
            ActionKind.FILL_REPORT: "ri-file-list-3-line",
        }[self.kind]


def _fr(date):
    return f"{timezone.localdate(date) if isinstance(date, datetime.datetime) else date:%d/%m/%Y}"


def _same_organization(assignment, company_field, prescriber_organization_field):
    """Acts done for the assignment's organization: its company, its prescriber organization, or none of them."""
    return Q(
        **{
            f"{company_field}_id": assignment.company_id,
            f"{prescriber_organization_field}_id": assignment.prescriber_organization_id,
        }
    )


def _job_applications(request, job_seeker):
    """Same scopes as job_seekers_views.JobApplicationTabView.get_job_applications."""
    if request.from_employer:
        scoped = JobApplication.objects.for_company(request.current_organization).filter(job_seeker=job_seeker)
    else:
        scoped = job_seeker.job_applications.prescriptions_of(
            request.user, request.current_organization
        ) | xp_ref_iae_job_applications(request).filter(job_seeker=job_seeker)
    if can_view_external_actions(job_seeker, request):
        return job_seeker.job_applications.annotate(user_can_see_details=Exists(scoped.filter(pk=OuterRef("pk"))))
    return scoped.annotate(user_can_see_details=Value(True))


def _job_application_url(request, job_application):
    if not job_application.user_can_see_details:
        return ""
    name = "apply:details_for_prescriber" if request.from_prescriber else "apply:details_for_company"
    return reverse(name, kwargs={"job_application_id": job_application.pk})


def _orientations(request, job_seeker):
    """Same scopes as job_seekers_views.OrientationsTabView.get_orientations."""
    scope = (
        {"sender_company": request.current_organization}
        if request.from_employer
        else {"sender_prescriber_organization": request.current_organization}
    )
    scoped = Orientation.objects.filter(beneficiary=job_seeker, **scope)
    if can_view_external_actions(job_seeker, request):
        return job_seeker.orientations.annotate(user_can_see_details=Exists(scoped.filter(pk=OuterRef("pk"))))
    return scoped.annotate(user_can_see_details=Value(True))


def advisor_acts(request, assignment):
    """The acts of the assignment's advisor for the job seeker that the user may see, the latest first."""
    job_seeker = assignment.job_seeker
    advisor = assignment.advisor
    acts = []
    if advisor is None:
        # An unknown advisor: the professional who recorded the assignment did not do its acts.
        return [Act(assignment.last_action_kind, assignment.last_action_at)]

    applications = {
        job_application.pk: job_application
        for job_application in _job_applications(request, job_seeker).select_related("to_company", "sender")
    }
    for job_application in applications.values():
        if job_application.sender_id == advisor.pk and (
            job_application.sender_company_id == assignment.company_id
            and job_application.sender_prescriber_organization_id == assignment.prescriber_organization_id
        ):
            acts.append(
                Act(
                    ActionKind.APPLY,
                    job_application.created_at,
                    f"À {job_application.to_company.display_name} · {job_application.get_state_display()}",
                    _job_application_url(request, job_application),
                )
            )
    for log in JobApplicationTransitionLog.objects.filter(
        job_application_id__in=list(applications),
        user=advisor,
        transition=JobApplicationWorkflow.TRANSITION_ACCEPT,
    ):
        job_application = applications[log.job_application_id]
        if assignment.company_id and job_application.to_company_id != assignment.company_id:
            continue
        # An employer who sent the application to their own company declared a hiring.
        hired = job_application.sender_id == advisor.pk and job_application.sender_company_id == assignment.company_id
        acts.append(
            Act(
                ActionKind.HIRE if hired else ActionKind.ACCEPT,
                log.timestamp,
                f"Chez {job_application.to_company.display_name}",
                _job_application_url(request, job_application),
            )
        )

    if request.from_iae_actor:
        diagnoses = EligibilityDiagnosis.objects.filter(job_seeker=job_seeker, author=advisor).filter(
            _same_organization(assignment, "author_siae", "author_prescriber_organization")
        )
        for diagnosis in diagnoses:
            # An employer's diagnosis only counts for their company: others do not see it on the job seeker page.
            if diagnosis.author_kind == AuthorKind.EMPLOYER and not (
                request.from_employer and diagnosis.author_siae_id == request.current_organization.pk
            ):
                continue
            acts.append(Act(ActionKind.IAE_ELIGIBILITY, diagnosis.created_at, _validity(diagnosis)))

    if request.from_prescriber or not request.from_iae_actor:
        diagnoses = GEIQEligibilityDiagnosis.objects.filter(job_seeker=job_seeker, author=advisor).filter(
            _same_organization(assignment, "author_geiq", "author_prescriber_organization")
        )
        for diagnosis in diagnoses:
            if diagnosis.author_geiq_id and not (
                request.from_employer and diagnosis.author_geiq_id == request.current_organization.pk
            ):
                continue
            acts.append(Act(ActionKind.GEIQ_ELIGIBILITY, diagnosis.created_at, _validity(diagnosis)))

    for report in job_seeker.pro_support_reports.filter(author=advisor).select_related("company"):
        if assignment.company_id and report.company_id != assignment.company_id:
            continue
        if can_view_pro_support_report(request, report):
            url = reverse("job_seekers_views:pro_support_report", kwargs={"public_id": job_seeker.public_id})
            acts.append(Act(ActionKind.FILL_REPORT, report.created_at, url=url))

    orientations = (
        _orientations(request, job_seeker)
        .filter(sender=advisor)
        .filter(_same_organization(assignment, "sender_company", "sender_prescriber_organization"))
        .select_related("service")
    )
    for orientation in orientations:
        url = ""
        if orientation.user_can_see_details:
            url = reverse("insertion_views:orientation_details_for_sender", kwargs={"orientation_id": orientation.pk})
        acts.append(
            Act(
                ActionKind.ORIENT,
                orientation.created_at,
                f"{orientation.service.name} · {orientation.get_status_display()}",
                url,
            )
        )

    if job_seeker.created_by_id == advisor.pk:
        acts.append(Act(ActionKind.CREATE, job_seeker.date_joined))

    # The last act is recorded on the assignment: shown even when its source is out of reach, as the existing
    # advisors tab does, and the only trace of an advisor who positioned themselves.
    if not any(act.kind == assignment.last_action_kind for act in acts):
        acts.append(Act(assignment.last_action_kind, assignment.last_action_at))

    return sorted(acts, key=lambda act: act.at, reverse=True)


def _validity(diagnosis):
    if diagnosis.expires_at and diagnosis.expires_at < timezone.localdate():
        return f"Expirée le {_fr(diagnosis.expires_at)}"
    if diagnosis.expires_at:
        return f"Valable jusqu’au {_fr(diagnosis.expires_at)}"
    return ""
