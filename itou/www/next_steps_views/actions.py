"""Expected actions of the "Prochaines étapes" experiment.

Each rule reads existing data and returns what the signed-in professional is expected to do, every action pointing
to the existing screen that handles it. Nothing is stored: an action disappears once the data says it is done.

Each action has a due date, from what waiting costs, and its group follows from it: late, today, this week, to watch.
The kind of action does not set its group: a job application received this morning is not more pressing than a PASS
IAE to suspend for weeks. Within a group, the nearest due date comes first, then the oldest action.
"""

import dataclasses
import datetime
import enum

from dateutil.relativedelta import relativedelta
from django.db.models import prefetch_related_objects
from django.urls import reverse
from django.utils import timezone

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import Approval, ProlongationRequest, Suspension
from itou.companies.enums import CompanyKind
from itou.companies.models import ProSupportReport
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog, JobApplicationWorkflow
from itou.users.enums import UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.www.job_seekers_views.views import _pro_support_request_company_email


# A report stays in the queue this long: whether the prescriber read it is not recorded.
PRO_SUPPORT_REPORT_TO_READ_DAYS = 30

# Due dates, in days from what starts the action. Provisional, to be settled with the team, except where noted.
# A job application gets an answer within a week. The prescriber's eligibility diagnosis is what the employer waits
# for to answer it, hence the same delay.
JOB_APPLICATION_ANSWER_DAYS = 7
# The platform reminds the prescriber of a pending prolongation request after 10 days
# (approvals/management/commands/prolongation_requests_chores.py). Never after the PASS IAE's end.
PROLONGATION_REQUEST_ANSWER_DAYS = 10
# A suspension may start up to a year back (Suspension.MAX_RETROACTIVITY_DURATION_DAYS), so waiting a little loses no
# day of PASS IAE; but once the person is hired elsewhere, this employer can no longer suspend it. A week, never after
# the PASS IAE's end nor past the retroactivity limit.
APPROVAL_SUSPENSION_DAYS = 7
# The report, from the contract's end; the prescriber's request for it has the same due date.
PRO_SUPPORT_REPORT_FILL_DAYS = 30
PRO_SUPPORT_REPORT_READ_DAYS = 7
# Beyond this many job applications in a group, the others are folded: the rarer actions must stay in sight.
JOB_APPLICATIONS_SHOWN = 3


NBSP = " "


class Group(enum.StrEnum):
    LATE = "late"
    TODAY = "today"
    WEEK = "week"
    WATCH = "watch"

    # Make the Enum work in Django's templates
    do_not_call_in_templates = enum.nonmember(True)


GROUPS = [
    (Group.LATE, "En retard", "L’échéance est passée."),
    (Group.TODAY, "Aujourd’hui", "L’échéance tombe aujourd’hui."),
    (Group.WEEK, "Cette semaine", "L’échéance tombe dans les 7 prochains jours."),
    (
        Group.WATCH,
        "À surveiller",
        f"Rien d’urgent{NBSP}: l’échéance est plus loin, ou c’est à quelqu’un d’autre d’agir.",
    ),
]
WEEK_DAYS = 7


def elapsed_display(since):
    """Time elapsed since a date, in the unit that reads best: "3 jours", "2 semaines", "5 mois"."""
    today = timezone.localdate()
    days = (today - since).days
    if days < 1:
        return "aujourd’hui"
    if days < 14:
        return f"{days}{NBSP}jour{'s' if days > 1 else ''}"
    if days < 60:
        return f"{days // 7}{NBSP}semaines"
    delta = relativedelta(today, since)
    return f"{delta.years * 12 + delta.months}{NBSP}mois"


def due_group(due):
    if due is None:
        return Group.WATCH
    today = timezone.localdate()
    if due < today:
        return Group.LATE
    if due == today:
        return Group.TODAY
    if due <= today + datetime.timedelta(days=WEEK_DAYS):
        return Group.WEEK
    return Group.WATCH


class Kind(enum.StrEnum):
    """The kind of action, which sets its icon (Remix Icons, the set shipped with itou-theme)."""

    APPROVAL_SUSPENSION = "ri-pause-circle-line"
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
    kind: Kind
    job_seeker: User
    title: str
    reason: str
    # The date the action started: the oldest comes first among those due the same day.
    since: datetime.date
    # The date it should be done by, which sets its group; None when it is up to someone else.
    due: datetime.date | None
    # Waiting actions have no button.
    url: str | None = None
    call_to_action: str | None = None
    status_label: str | None = None
    # Unique on the page, set once the queue is sorted.
    uid: str = ""

    @property
    def icon(self):
        return self.kind.value

    @property
    def group(self):
        return due_group(self.due)

    @property
    def due_display(self):
        if self.kind == Kind.JOB_APPLICATION:
            # What the person and the sender live: how long they have waited, since it was received.
            return f"En attente de réponse depuis {elapsed_display(self.since)}"
        if self.due is None:
            return ""
        late = (timezone.localdate() - self.due).days
        if late > 0:
            return f"En retard de {elapsed_display(self.due)}"
        if late == 0:
            return "À faire aujourd’hui"
        return f"À faire d’ici le {_fr(self.due)}"


def _date(value):
    return timezone.localdate(value) if isinstance(value, datetime.datetime) else value


def _after(value, days):
    return _date(value) + datetime.timedelta(days=days)


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
            kind=Kind.JOB_APPLICATION,
            job_seeker=job_application.job_seeker,
            title="Répondre à sa candidature",
            reason=(
                f"{JobApplicationState.NEW.label} reçue le {_fr(job_application.created_at)}"
                + (f", envoyée par {sender.display_name}." if sender else ".")
            ),
            since=_date(job_application.created_at),
            due=_after(job_application.created_at, JOB_APPLICATION_ANSWER_DAYS),
            url=reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            call_to_action="Étudier",
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
                    kind=Kind.APPROVAL_SUSPENSION,
                    job_seeker=job_seeker,
                    title="Suspendre le PASS IAE",
                    reason=(
                        f"Le contrat est terminé depuis le {_fr(end_date)} : "
                        "ses jours de PASS IAE continuent d’être décomptés tant qu’il n’est pas suspendu."
                    ),
                    since=end_date,
                    due=min(
                        _after(end_date, APPROVAL_SUSPENSION_DAYS),
                        _after(end_date, Suspension.MAX_RETROACTIVITY_DURATION_DAYS),
                        approval.end_at,
                    ),
                    url=reverse("approvals:suspend", kwargs={"approval_id": approval.pk}),
                    call_to_action="Suspendre",
                )
            if not job_seeker.last_contract_has_pro_support_report:
                yield Action(
                    kind=Kind.PRO_SUPPORT_REPORT_FILL,
                    job_seeker=job_seeker,
                    title="Remplir le bilan d’accompagnement",
                    reason=(
                        f"Contrat terminé le {_fr(end_date)}. Le bilan transmet au prescripteur "
                        "les freins restants, l’autonomie et la suite envisagée."
                    ),
                    since=end_date,
                    due=_after(end_date, PRO_SUPPORT_REPORT_FILL_DAYS),
                    url=reverse(
                        "job_seekers_views:create_pro_support_report", kwargs={"public_id": job_seeker.public_id}
                    ),
                    call_to_action="Remplir",
                )
        elif not job_seeker.last_contract_has_pro_support_report:
            yield Action(
                kind=Kind.PRO_SUPPORT_REPORT_FILL,
                job_seeker=job_seeker,
                title="Remplir le bilan d’accompagnement",
                reason=f"Le contrat se termine le {_fr(end_date)}. Le bilan peut être rempli dès maintenant.",
                since=end_date,
                due=_after(end_date, PRO_SUPPORT_REPORT_FILL_DAYS),
                url=reverse("job_seekers_views:create_pro_support_report", kwargs={"public_id": job_seeker.public_id}),
                call_to_action="Remplir",
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
            kind=Kind.WAITING,
            job_seeker=prolongation_request.approval.user,
            title="Prolongation du PASS IAE",
            reason=f"Demandée le {_fr(prolongation_request.created_at)}, en attente de la décision de {decider}.",
            since=_date(prolongation_request.created_at),
            due=None,
            status_label=prolongation_request.get_status_display(),
        )


def _employer_actions(request):
    company = request.current_organization
    yield from _new_job_applications(company)
    if request.from_iae_actor:
        yield from _end_of_contracts(company)
        yield from _prolongation_requests_sent(company)


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
            kind=Kind.PROLONGATION_REQUEST,
            job_seeker=prolongation_request.approval.user,
            title="Traiter la demande de prolongation",
            reason=(
                f"Demandée le {_fr(prolongation_request.created_at)}"
                + (f" par {requester.display_name}" if requester else "")
                + f". Le PASS IAE se termine le {_fr(prolongation_request.approval.end_at)}."
            ),
            since=_date(prolongation_request.created_at),
            due=min(
                _after(prolongation_request.created_at, PROLONGATION_REQUEST_ANSWER_DAYS),
                prolongation_request.approval.end_at,
            ),
            url=reverse(
                "approvals:prolongation_request_show",
                kwargs={"prolongation_request_id": prolongation_request.pk},
            ),
            call_to_action="Traiter",
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
            reason = f"Contrat terminé le {_fr(end_date)}, PASS IAE encore valide. C’est la SIAE qui remplit le bilan."
        else:
            reason = f"Le contrat se termine le {_fr(end_date)}. C’est la SIAE qui remplit le bilan."
        yield Action(
            kind=Kind.PRO_SUPPORT_REPORT_REQUEST,
            job_seeker=job_seeker,
            title="Demander le bilan d’accompagnement",
            reason=reason,
            since=end_date,
            # The SIAE's due date for the report.
            due=_after(end_date, PRO_SUPPORT_REPORT_FILL_DAYS),
            url=reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id}),
            call_to_action="Demander",
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
            kind=Kind.PRO_SUPPORT_REPORT_READ,
            job_seeker=report.job_seeker,
            title="Lire le bilan d’accompagnement",
            reason=(
                f"Rempli le {_fr(report.created_at)}"
                + (f" par {report.company.display_name}" if report.company else "")
                + f", à la fin du contrat le {_fr(report.contract_end_date)}."
            ),
            since=_date(report.created_at),
            due=_after(report.created_at, PRO_SUPPORT_REPORT_READ_DAYS),
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
            kind=Kind.ELIGIBILITY,
            job_seeker=job_seeker,
            title="Valider l’éligibilité IAE",
            reason=(
                f"Candidature du {_fr(job_application.created_at)} chez {job_application.to_company.display_name}, "
                "sans diagnostic d’éligibilité ni PASS IAE valide."
            ),
            since=_date(job_application.created_at),
            # The employer waits for it to answer the job application.
            due=_after(job_application.created_at, JOB_APPLICATION_ANSWER_DAYS),
            url=reverse("eligibility_views:update_iae", kwargs={"job_seeker_public_id": job_seeker.public_id}),
            call_to_action="Valider",
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
    """The actions expected from the signed-in professional, the nearest due date first, then the oldest."""
    if request.from_employer:
        actions = list(_employer_actions(request))
    elif request.from_prescriber:
        actions = list(_prescriber_actions(request))
    else:
        actions = []
    actions = sorted(actions, key=lambda action: (action.due or datetime.date.max, action.since))
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
    """The actions by group. Beyond JOB_APPLICATIONS_SHOWN job applications in a group, the others are folded."""
    groups = []
    for key, label, help_text in GROUPS:
        shown, folded = [], []
        for action in actions:
            if action.group != key:
                continue
            applications = sum(other.kind == Kind.JOB_APPLICATION for other in shown)
            if action.kind == Kind.JOB_APPLICATION and applications >= JOB_APPLICATIONS_SHOWN:
                folded.append(action)
            else:
                shown.append(action)
        groups.append(
            {
                "key": key,
                "label": label,
                "help": help_text,
                "actions": shown,
                "folded": folded,
                "count": len(shown) + len(folded),
            }
        )
    return groups


# Done today
# ------------------------------------------------------------------------------
# Read from what the platform already records, with its author and time: nothing is stored for the experiment.
# Shown to the user only, never aggregated: it measures their activity (see the RGPD validation before production).
# Not counted, as nothing records them: asking for a report by e-mail, reading a report.

TRANSITION_LABELS = {
    "process": "candidature mise à l’étude",
    "postpone": "candidature mise en attente",
    "accept": "embauche acceptée",
    "refuse": "candidature déclinée",
}


@dataclasses.dataclass
class Done:
    job_seeker: User
    label: str
    at: datetime.datetime


def _today_lookup(field):
    return {f"{field}__date": timezone.localdate()}


def _employer_done(request):
    company = request.current_organization
    logs = (
        JobApplicationTransitionLog.objects.filter(
            user=request.user,
            job_application__to_company=company,
            transition__in=TRANSITION_LABELS,
            **_today_lookup("timestamp"),
        )
        .select_related("job_application__job_seeker")
        .order_by("timestamp")
    )
    for log in logs:
        yield Done(log.job_application.job_seeker, TRANSITION_LABELS[log.transition], log.timestamp)
    suspensions = Suspension.objects.filter(
        created_by=request.user, siae=company, **_today_lookup("created_at")
    ).select_related("approval__user")
    for suspension in suspensions:
        yield Done(suspension.approval.user, f"PASS{NBSP}IAE suspendu", suspension.created_at)
    reports = ProSupportReport.objects.filter(
        author=request.user, company=company, **_today_lookup("created_at")
    ).select_related("job_seeker")
    for report in reports:
        yield Done(report.job_seeker, "bilan d’accompagnement envoyé", report.created_at)


def _prescriber_done(request):
    organization = request.current_organization
    prolongation_requests = ProlongationRequest.objects.filter(
        processed_by=request.user,
        prescriber_organization=organization,
        status__in=[ProlongationRequestStatus.GRANTED, ProlongationRequestStatus.DENIED],
        **_today_lookup("processed_at"),
    ).select_related("approval__user")
    for prolongation_request in prolongation_requests:
        decision = "acceptée" if prolongation_request.status == ProlongationRequestStatus.GRANTED else "refusée"
        yield Done(prolongation_request.approval.user, f"prolongation {decision}", prolongation_request.processed_at)
    diagnoses = EligibilityDiagnosis.objects.filter(
        author=request.user, author_prescriber_organization=organization, **_today_lookup("created_at")
    ).select_related("job_seeker")
    for diagnosis in diagnoses:
        yield Done(diagnosis.job_seeker, "éligibilité IAE validée", diagnosis.created_at)


def done_today(request):
    """What the signed-in professional did today among the expected actions, oldest first."""
    if request.from_employer:
        done = list(_employer_done(request))
    elif request.from_authorized_prescriber:
        done = list(_prescriber_done(request))
    else:
        done = []
    return sorted(done, key=lambda item: item.at)
