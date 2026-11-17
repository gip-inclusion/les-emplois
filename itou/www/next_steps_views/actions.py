"""Expected actions of the "Prochaines étapes" experiment.

Each rule reads existing data and returns what the signed-in professional is expected to do, every action pointing
to the existing screen that handles it. Nothing is stored: an action disappears once the data says it is done.
"""

import dataclasses
import datetime
import enum

from django.db.models import prefetch_related_objects
from django.urls import reverse
from django.utils import timezone

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import Approval, ProlongationRequest
from itou.companies.enums import CompanyKind
from itou.companies.models import ProSupportReport
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.rdv_insertion.enums import ParticipationStatus
from itou.rdv_insertion.models import Participation
from itou.users.enums import UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.www.job_seekers_views.views import _pro_support_request_company_email


# A report stays in the queue this long: whether the prescriber read it is not recorded.
PRO_SUPPORT_REPORT_TO_READ_DAYS = 30
# Older appointments with an undetermined status are left out: the queue is about what can still be acted upon.
APPOINTMENT_STATUS_TO_SPECIFY_DAYS = 30


NBSP = " "


class Group(enum.StrEnum):
    TODAY = "today"
    WEEK = "week"
    WATCH = "watch"

    # Make the Enum work in Django's templates
    do_not_call_in_templates = enum.nonmember(True)


GROUPS = [
    (Group.TODAY, "Aujourd’hui", "À faire sans attendre."),
    (Group.WEEK, "Cette semaine", "À traiter d’ici vendredi."),
    (Group.WATCH, "À surveiller", "Rien à faire tout de suite, à garder en tête."),
]


class Kind(enum.StrEnum):
    """The kind of action, which sets its icon (Remix Icons, the set shipped with itou-theme)."""

    APPROVAL_SUSPENSION = "ri-pause-circle-line"
    APPOINTMENT = "ri-calendar-check-line"
    ELIGIBILITY = "ri-shield-check-line"
    JOB_APPLICATION = "ri-file-user-line"
    PROLONGATION_REQUEST = "ri-time-line"
    PRO_SUPPORT_REPORT_FILL = "ri-file-edit-line"
    PRO_SUPPORT_REPORT_READ = "ri-file-text-line"
    PRO_SUPPORT_REPORT_REQUEST = "ri-mail-send-line"
    WAITING = "ri-hourglass-line"

    do_not_call_in_templates = enum.nonmember(True)


@dataclasses.dataclass
class Action:
    group: Group
    kind: Kind
    job_seeker: User
    title: str
    reason: str
    # The date the action became due: the oldest comes first in its group.
    since: datetime.date
    # Waiting actions have no button.
    url: str | None = None
    call_to_action: str | None = None
    status_label: str | None = None
    # The guided journey running the action in the side drawer, if any (see journeys.py).
    journey_url: str | None = None
    # Unique on the page, set once the queue is sorted.
    uid: str = ""

    @property
    def icon(self):
        return self.kind.value


def _journey_url(kind, pk):
    return reverse("next_steps_views:journey", kwargs={"kind": kind, "pk": pk})


def _date(value):
    return timezone.localdate(value) if isinstance(value, datetime.datetime) else value


def _fr(value):
    return f"{_date(value):%d/%m/%Y}"


# Employers
# ------------------------------------------------------------------------------


def _new_job_applications(company):
    job_applications = (
        JobApplication.objects.filter(to_company=company, state=JobApplicationState.NEW, archived_at=None)
        .select_related("job_seeker", "to_company", "sender_prescriber_organization", "sender_company")
        .order_by("created_at")
    )
    for job_application in job_applications:
        sender = job_application.sender_prescriber_organization or job_application.sender_company
        yield Action(
            group=Group.TODAY,
            kind=Kind.JOB_APPLICATION,
            job_seeker=job_application.job_seeker,
            title="Répondre à sa candidature",
            reason=(
                f"{JobApplicationState.NEW.label} reçue le {_fr(job_application.created_at)}"
                + (f", envoyée par {sender.display_name}." if sender else ".")
            ),
            since=_date(job_application.created_at),
            url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            call_to_action="Étudier",
            journey_url=_journey_url("candidature", job_application.pk),
        )


def _end_of_contracts(company):
    """Suspend the PASS IAE and fill the report once the contract ended; fill the report when it ends soon."""
    job_seekers = (
        User.objects.filter(kind=UserKind.JOB_SEEKER)
        .at_end_of_journey(siae=company)
        .with_end_of_journey(siae=company)
        .with_last_contract_end_date(siae=company)
        .with_last_contract_has_pro_support_report(siae=company)
    )
    for job_seeker in job_seekers:
        end_date = job_seeker.last_contract_end_date
        if job_seeker.last_contract_ended_with_valid_approval:
            approval = Approval.objects.filter(user=job_seeker).valid().order_by("-start_at").first()
            if approval and approval.can_be_suspended_by_siae(company):
                yield Action(
                    group=Group.TODAY,
                    kind=Kind.APPROVAL_SUSPENSION,
                    job_seeker=job_seeker,
                    title="Suspendre le PASS IAE",
                    reason=(
                        f"Le contrat est terminé depuis le {_fr(end_date)} : "
                        "ses jours de PASS IAE continuent d’être décomptés tant qu’il n’est pas suspendu."
                    ),
                    since=end_date,
                    url=reverse("approvals:suspend", kwargs={"approval_id": approval.pk}),
                    call_to_action="Suspendre",
                    journey_url=_journey_url("suspension", approval.pk),
                )
            if not job_seeker.last_contract_has_pro_support_report:
                yield Action(
                    group=Group.WEEK,
                    kind=Kind.PRO_SUPPORT_REPORT_FILL,
                    job_seeker=job_seeker,
                    title="Remplir le bilan d’accompagnement",
                    reason=(
                        f"Contrat terminé le {_fr(end_date)}. Le bilan transmet au prescripteur "
                        "les freins restants, l’autonomie et la suite envisagée."
                    ),
                    since=end_date,
                    url=reverse(
                        "job_seekers_views:create_pro_support_report", kwargs={"public_id": job_seeker.public_id}
                    ),
                    call_to_action="Remplir",
                    journey_url=_journey_url("bilan", job_seeker.public_id),
                )
        elif not job_seeker.last_contract_has_pro_support_report:
            yield Action(
                group=Group.WATCH,
                kind=Kind.PRO_SUPPORT_REPORT_FILL,
                job_seeker=job_seeker,
                title="Remplir le bilan d’accompagnement",
                reason=f"Le contrat se termine le {_fr(end_date)}. Le bilan peut être rempli dès maintenant.",
                since=end_date,
                url=reverse("job_seekers_views:create_pro_support_report", kwargs={"public_id": job_seeker.public_id}),
                call_to_action="Remplir",
                journey_url=_journey_url("bilan", job_seeker.public_id),
            )


def _appointments_with_undetermined_status(company):
    now = timezone.now()
    participations = (
        Participation.objects.filter(
            appointment__company=company,
            status=ParticipationStatus.UNKNOWN,
            appointment__canceled_at=None,
            appointment__start_at__lt=now,
            appointment__start_at__gte=now - datetime.timedelta(days=APPOINTMENT_STATUS_TO_SPECIFY_DAYS),
        )
        .select_related("job_seeker", "appointment")
        .order_by("appointment__start_at")
    )
    for participation in participations:
        appointment = participation.appointment
        yield Action(
            group=Group.WEEK,
            kind=Kind.APPOINTMENT,
            job_seeker=participation.job_seeker,
            title=f"Préciser le statut du rendez-vous du {_fr(appointment.start_at)}",
            reason=(
                f"{appointment.reason.rstrip('.')}. Statut : {ParticipationStatus.UNKNOWN.label}, "
                "il se renseigne dans RDV-Insertion."
            ),
            since=_date(appointment.start_at),
            url=reverse(
                "job_seekers_views:appointment_details",
                kwargs={
                    "public_id": participation.job_seeker.public_id,
                    "rdv_insertion_id": appointment.rdv_insertion_id,
                },
            ),
            call_to_action="Voir",
        )


def _prolongation_requests_sent(company):
    prolongation_requests = (
        ProlongationRequest.objects.filter(declared_by_siae=company, status=ProlongationRequestStatus.PENDING)
        .select_related("approval__user", "assigned_to", "prescriber_organization")
        .order_by("created_at")
    )
    for prolongation_request in prolongation_requests:
        decider = prolongation_request.assigned_to.get_full_name()
        if prolongation_request.prescriber_organization:
            decider += f" ({prolongation_request.prescriber_organization.display_name})"
        yield Action(
            group=Group.WATCH,
            kind=Kind.WAITING,
            job_seeker=prolongation_request.approval.user,
            title="Prolongation du PASS IAE",
            reason=f"Demandée le {_fr(prolongation_request.created_at)}, en attente de la décision de {decider}.",
            since=_date(prolongation_request.created_at),
            status_label=prolongation_request.get_status_display(),
        )


def _employer_actions(request):
    company = request.current_organization
    yield from _new_job_applications(company)
    if request.from_iae_actor:
        yield from _end_of_contracts(company)
        yield from _prolongation_requests_sent(company)
    yield from _appointments_with_undetermined_status(company)


# Prescribers
# ------------------------------------------------------------------------------


def _assigned_job_seekers(request):
    return User.objects.filter(
        pk__in=User.objects.assigned_job_seeker_ids(request.user, request.current_organization, archived=False)
    )


def _prolongation_requests_to_process(request):
    prolongation_requests = (
        ProlongationRequest.objects.filter(
            prescriber_organization=request.current_organization,
            assigned_to=request.user,
            status=ProlongationRequestStatus.PENDING,
        )
        .select_related("approval__user", "declared_by_siae")
        .order_by("created_at")
    )
    for prolongation_request in prolongation_requests:
        requester = prolongation_request.declared_by_siae
        yield Action(
            group=Group.TODAY,
            kind=Kind.PROLONGATION_REQUEST,
            job_seeker=prolongation_request.approval.user,
            title="Traiter la demande de prolongation",
            reason=(
                f"Demandée le {_fr(prolongation_request.created_at)}"
                + (f" par {requester.display_name}" if requester else "")
                + f". Le PASS IAE se termine le {_fr(prolongation_request.approval.end_at)}."
            ),
            since=_date(prolongation_request.created_at),
            url=reverse(
                "approvals:prolongation_request_show",
                kwargs={"prolongation_request_id": prolongation_request.pk},
            ),
            call_to_action="Traiter",
            journey_url=_journey_url("prolongation", prolongation_request.pk),
        )


def _pro_support_reports_to_request(request):
    """Only the SIAE fills the report: the prescriber asks for it, from the job seeker's page."""
    job_seekers = (
        _assigned_job_seekers(request)
        .at_end_of_journey()
        .with_end_of_journey()
        .with_last_contract_end_date(siae=None)
        .with_last_contract_has_pro_support_report(siae=None)
        .filter(last_contract_has_pro_support_report=False)
        # Without the company's e-mail, the request cannot be prepared: the button leads to the job seeker's page.
        .annotate(company_email=_pro_support_request_company_email())
    )
    for job_seeker in job_seekers:
        end_date = job_seeker.last_contract_end_date
        if job_seeker.last_contract_ended_with_valid_approval:
            group = Group.WEEK
            reason = f"Contrat terminé le {_fr(end_date)}, PASS IAE encore valide. C’est la SIAE qui remplit le bilan."
        else:
            group = Group.WATCH
            reason = f"Le contrat se termine le {_fr(end_date)}. C’est la SIAE qui remplit le bilan."
        yield Action(
            group=group,
            kind=Kind.PRO_SUPPORT_REPORT_REQUEST,
            job_seeker=job_seeker,
            title="Demander le bilan d’accompagnement",
            reason=reason,
            since=end_date,
            url=reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id}),
            call_to_action="Demander",
            journey_url=_journey_url("demande-bilan", job_seeker.public_id) if job_seeker.company_email else None,
        )


def _pro_support_reports_to_read(request):
    # Same scope as can_view_pro_support_report().
    job_seeker_ids = JobSeekerAssignment.objects.assigned_to(
        request.user, request.current_organization, from_all_coworkers=True
    ).values("job_seeker")
    reports = (
        ProSupportReport.objects.filter(
            job_seeker__in=job_seeker_ids,
            created_at__gte=timezone.now() - datetime.timedelta(days=PRO_SUPPORT_REPORT_TO_READ_DAYS),
        )
        .select_related("job_seeker", "company")
        .order_by("created_at")
    )
    for report in reports:
        yield Action(
            group=Group.WEEK,
            kind=Kind.PRO_SUPPORT_REPORT_READ,
            job_seeker=report.job_seeker,
            title="Lire le bilan d’accompagnement",
            reason=(
                f"Rempli le {_fr(report.created_at)}"
                + (f" par {report.company.display_name}" if report.company else "")
                + f", à la fin du contrat le {_fr(report.contract_end_date)}."
            ),
            since=_date(report.created_at),
            url=reverse("job_seekers_views:pro_support_report", kwargs={"public_id": report.public_id}),
            call_to_action="Lire",
        )


def _eligibility_to_validate(request):
    """A pending job application to an SIAE, without a valid eligibility diagnosis nor PASS IAE."""
    job_seekers = (
        _assigned_job_seekers(request)
        .eligibility_pending()
        .filter(
            job_applications__state__in=JobApplicationWorkflow.PENDING_STATES,
            job_applications__to_company__kind__in=CompanyKind.siae_kinds(),
        )
        .distinct()
    )
    for job_seeker in job_seekers:
        job_application = (
            job_seeker.job_applications.filter(
                state__in=JobApplicationWorkflow.PENDING_STATES, to_company__kind__in=CompanyKind.siae_kinds()
            )
            .select_related("to_company")
            .order_by("created_at")
            .first()
        )
        yield Action(
            group=Group.WEEK,
            kind=Kind.ELIGIBILITY,
            job_seeker=job_seeker,
            title="Valider l’éligibilité IAE",
            reason=(
                f"Candidature du {_fr(job_application.created_at)} chez {job_application.to_company.display_name}, "
                "sans diagnostic d’éligibilité ni PASS IAE valide."
            ),
            since=_date(job_application.created_at),
            url=reverse("eligibility_views:update_iae", kwargs={"job_seeker_public_id": job_seeker.public_id}),
            call_to_action="Valider",
            journey_url=_journey_url("eligibilite", job_seeker.public_id),
        )


def _prescriber_actions(request):
    if not request.from_authorized_prescriber:
        # The rules below are all about the IAE journey, which authorized prescribers follow.
        return
    yield from _prolongation_requests_to_process(request)
    yield from _pro_support_reports_to_request(request)
    yield from _pro_support_reports_to_read(request)
    yield from _eligibility_to_validate(request)


# Queue
# ------------------------------------------------------------------------------


def expected_actions(request):
    """The actions expected from the signed-in professional, oldest first."""
    if request.from_employer:
        actions = list(_employer_actions(request))
    elif request.from_prescriber:
        actions = list(_prescriber_actions(request))
    else:
        actions = []
    actions = sorted(actions, key=lambda action: action.since)
    for index, action in enumerate(actions):
        action.uid = f"next-step-{index}"
    return actions


def describe_job_seekers(actions, can_view_personal_information):
    """Who each action is about, as in the prototype: the name, then the age and the city, if the user may see them."""
    prefetch_related_objects([action.job_seeker for action in actions], "jobseeker_profile")
    for action in actions:
        job_seeker = action.job_seeker
        action.user_can_view_personal_information = can_view_personal_information(job_seeker)
        details = []
        if action.user_can_view_personal_information:
            if (age := job_seeker.jobseeker_profile.age) is not None:
                details.append(f"{age}{NBSP}ans")
            if job_seeker.city:
                details.append(job_seeker.city)
        action.job_seeker_details = " · ".join(details)


def group_actions(actions):
    return [
        {"key": key, "label": label, "help": help_text, "actions": [a for a in actions if a.group == key]}
        for key, label, help_text in GROUPS
    ]
