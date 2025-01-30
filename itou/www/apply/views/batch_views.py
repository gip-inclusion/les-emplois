import enum
import logging
from collections import namedtuple

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template import loader
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from django_xworkflows import models as xwf_models

from itou.companies.models import Company
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils.auth import check_user
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.session import SessionNamespace
from itou.utils.templatetags.str_filters import pluralizefr
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    BatchPostponeForm,
    JobApplicationRefusalJobSeekerAnswerForm,
    JobApplicationRefusalPrescriberAnswerForm,
    JobApplicationRefusalReasonForm,
    _get_orienter_and_prescriber_nb,
)


logger = logging.getLogger(__name__)


def _get_and_lock_received_applications(request, application_ids, lock=True):
    company = get_current_company_or_404(request)
    qs = company.job_applications_received.filter(pk__in=application_ids)
    if lock:
        qs = qs.select_for_update()
    applications = list(qs)
    if mismatch_nb := len(application_ids) - len(applications):
        if mismatch_nb > 1:
            messages.error(
                request, f"{mismatch_nb} candidatures sélectionnées n’existent plus ou ont été transférées."
            )
        else:
            messages.error(request, "Une candidature sélectionnée n’existe plus ou a été transférée.")
    return applications


@check_user(lambda user: user.is_employer)
@require_POST
def archive(request):
    next_url = get_safe_url(request, "next_url")
    if next_url is None:
        # This is somewhat extreme but will force developpers to always provide a proper next_url
        raise Http404
    applications = _get_and_lock_received_applications(request, request.POST.getlist("application_ids"))

    archived_ids = []

    for job_application in applications:
        if job_application.can_be_archived:
            archived_ids.append(job_application.pk)
        elif job_application.archived_at:
            messages.warning(
                request,
                f"La candidature de {job_application.job_seeker.get_full_name()} est déjà archivée.",
                extra_tags="toast",
            )
        else:
            messages.error(
                request,
                (
                    f"La candidature de {job_application.job_seeker.get_full_name()} n’a pas pu être archivée "
                    f"car elle est au statut « {job_application.get_state_display()} »."
                ),
                extra_tags="toast",
            )

    archived_nb = JobApplication.objects.filter(pk__in=archived_ids).update(
        archived_at=timezone.now(),
        archived_by=request.user,
    )

    if archived_nb > 1:
        messages.success(request, f"{archived_nb} candidatures ont bien été archivées.", extra_tags="toast")
    elif archived_nb == 1:
        messages.success(request, "1 candidature a bien été archivée.", extra_tags="toast")

    logger.info(
        "user=%s batch archived %s applications: %s",
        request.user.pk,
        archived_nb,
        ",".join(str(app_uid) for app_uid in archived_ids),
    )
    return HttpResponseRedirect(next_url)


@check_user(lambda user: user.is_employer)
@require_POST
def postpone(request):
    next_url = get_safe_url(request, "next_url")
    if next_url is None:
        # This is somewhat extreme but will force developpers to always provide a proper next_url
        raise Http404
    applications = _get_and_lock_received_applications(request, request.POST.getlist("application_ids"))

    form = BatchPostponeForm(job_seeker_nb=None, data=request.POST)

    if not form.is_valid():
        # This is unlikely since the form is quite simple and the answer field is required
        messages.error(request, "Les candidatures n’ont pas pu être mises en attente.")
        logger.error(
            "user=%s tried to batch postponed %s applications but the form wasn't valid",
            request.user.pk,
            len(applications),
        )
    else:
        postponed_ids = []
        for job_application in applications:
            if job_application.state == JobApplicationState.POSTPONED:
                messages.warning(
                    request,
                    f"La candidature de {job_application.job_seeker.get_full_name()} est déjà mise en attente.",
                    extra_tags="toast",
                )
                continue
            try:
                # After each successful transition, a save() is performed by django-xworkflows.
                job_application.answer = form.cleaned_data["answer"]
                job_application.postpone(user=request.user)
            except xwf_models.InvalidTransitionError:
                messages.error(
                    request,
                    (
                        f"La candidature de {job_application.job_seeker.get_full_name()} n’a pas pu être mise en "
                        f"attente car elle est au statut « {job_application.get_state_display()} »."
                    ),
                    extra_tags="toast",
                )
            else:
                postponed_ids.append(job_application.pk)

        postponed_nb = len(postponed_ids)
        if postponed_nb:
            messages.success(
                request,
                (
                    f"{postponed_nb} candidatures ont bien été mises en attente."
                    if postponed_nb > 1
                    else "La candidature a bien été mise en attente."
                ),
                extra_tags="toast",
            )
        logger.info(
            "user=%s batch postponed %s applications: %s",
            request.user.pk,
            postponed_nb,
            ",".join(str(app_uid) for app_uid in postponed_ids),
        )
    return HttpResponseRedirect(next_url)


BATCH_REFUSE_SESSION_KIND = "job-applications-batch-refuse"


class RefuseViewStep(enum.StrEnum):
    REASON = "reason"
    JOB_SEEKER_ANSWER = "job-seeker-answer"
    PRESCRIBER_ANSWER = "prescriber-answer"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


def _start_refuse_wizard(request, *, application_ids, next_url):
    if next_url is None:
        # This is somewhat extreme but will force developpers to always provide a proper next_url
        raise Http404
    applications = _get_and_lock_received_applications(request, application_ids, lock=False)
    application_ids = []
    for job_application in applications:
        if job_application.refuse.is_available():
            application_ids.append(job_application.pk)
        else:
            messages.error(
                request,
                (
                    f"La candidature de {job_application.job_seeker.get_full_name()} ne peut pas être refusée "
                    f"car elle est au statut « {job_application.get_state_display()} »."
                ),
                extra_tags="toast",
            )

    if not application_ids:
        return HttpResponseRedirect(next_url)
    refuse_session = SessionNamespace.create_uuid_namespace(
        request.session,
        data={
            "config": {"session_kind": BATCH_REFUSE_SESSION_KIND, "reset_url": next_url},
            "application_ids": application_ids,
        },
    )
    return HttpResponseRedirect(
        reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session.name, "step": RefuseViewStep.REASON}
        )
    )


@check_user(lambda user: user.is_employer)
@require_POST
def refuse(request):
    return _start_refuse_wizard(
        request, application_ids=request.POST.getlist("application_ids"), next_url=get_safe_url(request, "next_url")
    )


class RefuseWizardView(UserPassesTestMixin, TemplateView):
    url_name = None  # Set by `RefuseWizardView.as_view` call in urls.py
    expected_session_kind = BATCH_REFUSE_SESSION_KIND
    STEPS = [
        RefuseViewStep.REASON,
        RefuseViewStep.JOB_SEEKER_ANSWER,
        RefuseViewStep.PRESCRIBER_ANSWER,
    ]

    template_name = "apply/process_refuse.html"

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_employer

    def load_session(self, session_uuid):
        wizard_session = SessionNamespace(self.request.session, session_uuid)
        if not wizard_session.exists():
            raise Http404
        if (session_kind := wizard_session.get("config", {}).get("session_kind")) != self.expected_session_kind:
            logger.warning(f"Trying to reuse invalid session with kind={session_kind}")
            raise Http404
        self.wizard_session = wizard_session
        self.reset_url = wizard_session.get("config", {}).get("reset_url")
        if self.reset_url is None:
            # Session should have been initialized with a reset_url and this RefuseWizardView expects one
            raise Http404

    def setup(self, request, *args, session_uuid, step, **kwargs):
        super().setup(request, *args, **kwargs)
        self.load_session(session_uuid)

        # Batch refuse specific logic
        self.applications = _get_and_lock_received_applications(
            request,
            self.wizard_session.get("application_ids", []),
            lock=False,
        )
        if not self.applications:
            raise Http404
        elif len(self.applications) != len(self.wizard_session.get("application_ids", [])):
            # Update the list
            self.wizard_session.set("application_ids", [application.pk for application in self.applications])

        # Check step consistency
        self.steps = self.get_steps()
        try:
            step = RefuseViewStep(step)
        except ValueError:
            raise Http404
        if step not in self.steps:
            raise Http404

        self.step = step
        self.next_step = self.get_next_step()

        self.form = self.get_form(self.step, data=self.request.POST if self.request.method == "POST" else None)

    def get_steps(self):
        if any(
            job_application.sender_kind == job_applications_enums.SenderKind.PRESCRIBER
            for job_application in self.applications
        ):
            return self.STEPS
        return [
            RefuseViewStep.REASON,
            RefuseViewStep.JOB_SEEKER_ANSWER,
        ]

    def get_next_step(self):
        next_step_index = self.steps.index(self.step) + 1
        if next_step_index >= len(self.steps):
            return None
        return self.steps[next_step_index]

    def get_previous_step(self):
        prev_step_index = self.steps.index(self.step) - 1
        if prev_step_index < 0:
            return None
        return self.steps[prev_step_index]

    def get_step_url(self, step):
        return reverse(self.url_name, kwargs={"session_uuid": self.wizard_session.name, "step": step})

    def get_form_initial(self, step):
        initial_data = self.wizard_session.get(step, {})
        # XXX: check if we want to override job_seeker_answer even if one is present ?
        if step == RefuseViewStep.JOB_SEEKER_ANSWER and not initial_data.get("job_seeker_answer"):
            refusal_reason = self.wizard_session.get(RefuseViewStep.REASON, {}).get("refusal_reason")

            if refusal_reason:
                initial_data["job_seeker_answer"] = loader.render_to_string(
                    f"apply/refusal_messages/{refusal_reason}.txt",
                    context={
                        "to_company": get_current_company_or_404(self.request),
                    }
                    if refusal_reason == job_applications_enums.RefusalReason.NON_ELIGIBLE
                    else {},
                    request=self.request,
                )
        return initial_data

    def get_form_kwargs(self):
        return {"job_applications": self.applications}

    def get_form_class(self, step):
        return {
            RefuseViewStep.REASON: JobApplicationRefusalReasonForm,
            RefuseViewStep.JOB_SEEKER_ANSWER: JobApplicationRefusalJobSeekerAnswerForm,
            RefuseViewStep.PRESCRIBER_ANSWER: JobApplicationRefusalPrescriberAnswerForm,
        }[step]

    def get_form(self, step, data):
        return self.get_form_class(step)(initial=self.get_form_initial(step), data=data, **self.get_form_kwargs())

    def get_context_data(self, **kwargs):
        orienter_nb, prescriber_nb = _get_orienter_and_prescriber_nb(self.applications)
        if orienter_nb and not prescriber_nb:
            to_prescriber = pluralizefr(orienter_nb, "à l’orienteur,aux orienteurs")
            the_prescriber = pluralizefr(orienter_nb, "l’orienteur,les orienteurs")
        elif prescriber_nb and not orienter_nb:
            to_prescriber = pluralizefr(prescriber_nb, "au prescripteur,aux prescripteurs")
            the_prescriber = pluralizefr(prescriber_nb, "le prescripteur,les prescripteurs")
        else:
            # orienter_nb & prescriber_nb might both be equal to 0 here
            to_prescriber = "aux prescripteurs/orienteurs"
            the_prescriber = "les prescripteurs/orienteurs"

        Steps = namedtuple("Steps", ["current", "step1", "count", "next", "prev"])
        context = super().get_context_data(**kwargs) | {
            "job_applications": self.applications,
            "can_view_personal_information": True,  # SIAE members have access to personal info
            "matomo_custom_title": "Candidatures refusées",
            "matomo_event_name": f"batch-refuse-applications-{self.step}-submit",
            # Compatibility with current process_refuse.html
            "wizard": {
                "steps": Steps(
                    current=self.step,
                    step1=self.steps.index(self.step) + 1,
                    count=len(self.steps),
                    next=self.next_step,
                    prev=self.get_step_url(self.get_previous_step()) if self.get_previous_step() is not None else None,
                ),
                "form": self.form,
                "management_form": "",
            },
            "form": self.form,
            "reset_url": self.reset_url,
            "RefuseViewStep": RefuseViewStep,
            "to_prescriber": to_prescriber,
            "the_prescriber": the_prescriber,
            "with_prescriber": orienter_nb or prescriber_nb,
            "job_seeker_nb": len(set(job_application.job_seeker_id for job_application in self.applications)),
        }
        if self.step != RefuseViewStep.REASON:
            reason_data = self.wizard_session.get(RefuseViewStep.REASON, {})

            if refusal_reason := reason_data.get("refusal_reason"):
                context["refusal_reason_label"] = job_applications_enums.RefusalReason(refusal_reason).label
            else:
                context["refusal_reason_label"] = "Non renseigné"
            context["refusal_reason_shared_with_job_seeker"] = reason_data.get("refusal_reason_shared_with_job_seeker")

        return context

    def find_step_with_invalid_data_until_step(self, step):
        """Return the step with invalid data or None if everything is fine"""
        for previous_step in self.steps:
            if previous_step == step:
                return None
            if self.wizard_session.get(previous_step) is self.wizard_session.NOT_SET:
                return previous_step
            form = self.get_form(previous_step, data=self.wizard_session.get(previous_step, {}))
            if not form.is_valid():
                return previous_step
        return None

    def get(self, request, *args, **kwargs):
        if invalid_step := self.find_step_with_invalid_data_until_step(self.step):
            return HttpResponseRedirect(self.get_step_url(invalid_step))
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.wizard_session.set(self.step, self.form.cleaned_data)
            if self.next_step:
                return HttpResponseRedirect(self.get_step_url(self.next_step))
            else:
                if invalid_step := self.find_step_with_invalid_data_until_step(self.step):
                    messages.warning(request, "Certaines informations sont absentes ou invalides")
                    return HttpResponseRedirect(self.get_step_url(invalid_step))
                self.done()
                return HttpResponseRedirect(self.reset_url)
        context = self.get_context_data(**kwargs)
        return self.render_to_response(context)

    def done(self):
        refuse_session_data = self.wizard_session.as_dict()
        # We're done, refuse all applications !
        refused_ids = []
        for job_application in _get_and_lock_received_applications(
            self.request,
            [application.pk for application in self.applications],
        ):
            job_application.refusal_reason = refuse_session_data[RefuseViewStep.REASON]["refusal_reason"]
            job_application.refusal_reason_shared_with_job_seeker = refuse_session_data[RefuseViewStep.REASON][
                "refusal_reason_shared_with_job_seeker"
            ]
            job_application.answer = refuse_session_data[RefuseViewStep.JOB_SEEKER_ANSWER]["job_seeker_answer"]
            # This step/field might be absent
            job_application.answer_to_prescriber = refuse_session_data.get(RefuseViewStep.PRESCRIBER_ANSWER, {}).get(
                "prescriber_answer", ""
            )
            try:
                job_application.refuse(user=self.request.user)
            except xwf_models.InvalidTransitionError:
                messages.error(
                    self.request,
                    (
                        f"La candidature de {job_application.job_seeker.get_full_name()} n’a pas pu être refusée "
                        f"car elle est au statut « {job_application.get_state_display()} »."
                    ),
                    extra_tags="toast",
                )
            else:
                refused_ids.append(job_application.pk)
        refused_nb = len(refused_ids)
        if refused_nb:
            messages.success(
                self.request,
                (
                    f"{refused_nb} candidatures ont bien été refusées."
                    if refused_nb > 1
                    else f"La candidature de {self.applications[0].job_seeker.get_full_name()} a bien été refusée."
                ),
                extra_tags="toast",
            )
        logger.info(
            "user=%s batch refused %s applications: %s",
            self.request.user.pk,
            refused_nb,
            ",".join(str(app_uid) for app_uid in refused_ids),
        )
        self.wizard_session.delete()


@check_user(lambda user: user.is_employer)
@require_POST
def transfer(request):
    next_url = get_safe_url(request, "next_url")
    if next_url is None:
        # This is somewhat extreme but will force developpers to always provide a proper next_url
        raise Http404
    target_company = get_object_or_404(
        Company.objects.filter(pk__in={org.pk for org in request.organizations}),
        pk=request.POST.get("target_company_id"),
    )
    applications = _get_and_lock_received_applications(request, request.POST.getlist("application_ids"))
    transfered_ids = []
    for job_application in applications:
        try:
            job_application.transfer(user=request.user, target_company=target_company)
            transfered_ids.append(job_application.pk)
        except (ValidationError, xwf_models.InvalidTransitionError):
            error_msg = f"La candidature de {job_application.job_seeker.get_full_name()} n’a pas pu être transférée"
            if not job_application.transfer.is_available():
                error_msg += f" car elle est au statut « {job_application.get_state_display()} »."
            else:
                error_msg += "."
            messages.error(request, error_msg, extra_tags="toast")

    transfered_nb = len(transfered_ids)
    if transfered_nb > 1:
        messages.success(request, f"{transfered_nb} candidatures ont bien été transférées.", extra_tags="toast")
    elif transfered_nb == 1:
        messages.success(request, "1 candidature a bien été transférée.", extra_tags="toast")
    logger.info(
        "user=%s batch transfered %s applications: %s",
        request.user.pk,
        transfered_nb,
        ",".join(str(app_uid) for app_uid in transfered_ids),
    )
    return HttpResponseRedirect(next_url)
