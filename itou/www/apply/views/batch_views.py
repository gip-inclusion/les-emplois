import enum
import logging

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template import loader
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_xworkflows import models as xwf_models

from itou.companies.models import Company
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils.auth import check_user
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.templatetags.str_filters import pluralizefr
from itou.utils.urls import get_safe_url
from itou.www.apply.forms import (
    BatchPostponeForm,
    JobApplicationRefusalJobSeekerAnswerForm,
    JobApplicationRefusalPrescriberAnswerForm,
    JobApplicationRefusalReasonForm,
    _get_orienter_and_prescriber_nb,
)
from itou.www.utils.wizard import WizardView


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


class RefuseViewStep(enum.StrEnum):
    REASON = "reason"
    JOB_SEEKER_ANSWER = "job-seeker-answer"
    PRESCRIBER_ANSWER = "prescriber-answer"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


class RefuseTunnel(enum.StrEnum):
    SINGLE = "single"
    BATCH = "batch"


def _start_refuse_wizard(request, *, application_ids, next_url, from_detail_view=False):
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

    return RefuseWizardView.initialize_session_and_start(
        request,
        reset_url=next_url,
        extra_session_data={
            "config": {
                "tunnel": RefuseTunnel.SINGLE if from_detail_view else RefuseTunnel.BATCH,
            },
            "application_ids": application_ids,
        },
    )


@check_user(lambda user: user.is_employer)
@require_POST
def refuse(request):
    return _start_refuse_wizard(
        request, application_ids=request.POST.getlist("application_ids"), next_url=get_safe_url(request, "next_url")
    )


class RefuseWizardView(UserPassesTestMixin, WizardView):
    url_name = "apply:batch_refuse_steps"
    expected_session_kind = "job-applications-batch-refuse"

    steps_config = {
        RefuseViewStep.REASON: JobApplicationRefusalReasonForm,
        RefuseViewStep.JOB_SEEKER_ANSWER: JobApplicationRefusalJobSeekerAnswerForm,
        RefuseViewStep.PRESCRIBER_ANSWER: JobApplicationRefusalPrescriberAnswerForm,
    }

    template_name = "apply/process_refuse.html"

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_employer

    def load_session(self, session_uuid):
        super().load_session(session_uuid)
        self.tunnel = self.wizard_session.get("config", {}).get("tunnel", RefuseTunnel.BATCH)

    def setup_wizard(self):
        super().setup_wizard()
        # Batch refuse specific logic
        self.applications = _get_and_lock_received_applications(
            self.request,
            self.wizard_session.get("application_ids", []),
            lock=False,
        )
        if not self.applications:
            raise Http404
        elif len(self.applications) != len(self.wizard_session.get("application_ids", [])):
            # Update the list
            self.wizard_session.set("application_ids", [application.pk for application in self.applications])

    def get_steps(self):
        if any(
            job_application.sender_kind == job_applications_enums.SenderKind.PRESCRIBER
            for job_application in self.applications
        ):
            return super().get_steps()
        return [
            RefuseViewStep.REASON,
            RefuseViewStep.JOB_SEEKER_ANSWER,
        ]

    def get_form_initial(self, step):
        initial_data = super().get_form_initial(step)
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

    def get_form_kwargs(self, step):
        return super().get_form_kwargs(step) | {"job_applications": self.applications}

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

        if self.tunnel == RefuseTunnel.BATCH:
            matomo_custom_title = "Candidatures refusées"
            matomo_event_name = f"batch-refuse-applications-{self.step}-submit"
        else:
            matomo_custom_title = "Candidature refusée"
            matomo_event_name = f"batch-refuse-application-{self.step}-submit"
        context = super().get_context_data(**kwargs) | {
            "job_applications": self.applications,
            "can_view_personal_information": True,  # SIAE members have access to personal info
            "matomo_custom_title": matomo_custom_title,
            "matomo_event_name": matomo_event_name,
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
            f"user=%s {self.tunnel} refused %s applications: %s",
            self.request.user.pk,
            refused_nb,
            ",".join(str(app_uid) for app_uid in refused_ids),
        )

        return self.reset_url


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
    transferred_ids = []
    for job_application in applications:
        try:
            job_application.transfer(user=request.user, target_company=target_company)
            transferred_ids.append(job_application.pk)
        except (ValidationError, xwf_models.InvalidTransitionError):
            error_msg = f"La candidature de {job_application.job_seeker.get_full_name()} n’a pas pu être transférée"
            if not job_application.transfer.is_available():
                error_msg += f" car elle est au statut « {job_application.get_state_display()} »."
            else:
                error_msg += "."
            messages.error(request, error_msg, extra_tags="toast")

    transferred_nb = len(transferred_ids)
    if transferred_nb > 1:
        messages.success(request, f"{transferred_nb} candidatures ont bien été transférées.", extra_tags="toast")
    elif transferred_nb == 1:
        messages.success(request, "1 candidature a bien été transférée.", extra_tags="toast")
    logger.info(
        "user=%s batch transferred %s applications: %s",
        request.user.pk,
        transferred_nb,
        ",".join(str(app_uid) for app_uid in transferred_ids),
    )
    return HttpResponseRedirect(next_url)
