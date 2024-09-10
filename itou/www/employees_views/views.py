import datetime
import logging
import urllib.parse

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import DetailView

from itou.approvals.models import (
    ProlongationRequest,
)
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.immersion_facile import immersion_search_url
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.urls import get_safe_url


logger = logging.getLogger(__name__)


SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE = datetime.timedelta(days=365)


class EmployeeDetailView(LoginRequiredMixin, DetailView):
    model = User
    queryset = User.objects.filter(kind=UserKind.JOB_SEEKER)
    template_name = "employees/detail.html"
    slug_field = "public_id"
    slug_url_kwarg = "public_id"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        if request.user.is_authenticated:
            self.siae = get_current_company_or_404(request)

            if not self.siae.is_subject_to_eligibility_rules:
                raise PermissionDenied

    def get_job_application(self, employee):
        return (
            JobApplication.objects.filter(
                job_seeker=employee,
                state=JobApplicationState.ACCEPTED,
                to_company=self.siae,
                # To be consistent with previous ApprovalDetailView
                # an approval is needed
                approval__isnull=False,
            )
            .select_related(
                "approval__user__jobseeker_profile",
                "eligibility_diagnosis",
                "eligibility_diagnosis__author_siae",
                "eligibility_diagnosis__author_prescriber_organization",
                "eligibility_diagnosis__job_seeker",
                "sender_prescriber_organization",
            )
            .prefetch_related(
                "approval__suspension_set",
                Prefetch(
                    "approval__prolongationrequest_set",
                    queryset=ProlongationRequest.objects.select_related(
                        "declared_by", "validated_by", "processed_by", "prescriber_organization"
                    ),
                ),
            )
            .last()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["siae"] = self.siae
        job_application = self.get_job_application(self.object)
        if job_application:
            approval = job_application.approval
        else:
            # This shouldn't be possible except if the job application has been deleted
            # in this case, use the last approval
            approval = self.object.approvals.order_by("-end_at").first()

        context["can_view_personal_information"] = True  # SIAE members have access to personal info
        context["can_edit_personal_information"] = self.request.user.can_edit_personal_information(approval.user)
        context["approval_can_be_suspended_by_siae"] = approval.can_be_suspended_by_siae(self.siae)
        context["approval_can_be_prolonged"] = approval.can_be_prolonged
        context["approval"] = approval
        context["job_application"] = job_application
        context["matomo_custom_title"] = "Profil salarié"
        context["eligibility_diagnosis"] = job_application and job_application.get_eligibility_diagnosis()
        context["approval_deletion_form_url"] = None
        context["back_url"] = get_safe_url(self.request, "back_url", fallback_url=reverse_lazy("approvals:list"))
        context["link_immersion_facile"] = None

        if approval.is_in_progress:
            # suspension_set has already been loaded via prefetch_related for the remainder computation
            for suspension in sorted(approval.suspension_set.all(), key=lambda s: s.start_at):
                if suspension.is_in_progress:
                    suspension_duration = timezone.localdate() - suspension.start_at
                    has_hirings_after_suspension = False
                else:
                    suspension_duration = suspension.duration
                    has_hirings_after_suspension = (
                        approval.jobapplication_set.accepted().filter(hiring_start_at__gte=suspension.end_at).exists()
                    )

                if (
                    suspension_duration > SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE
                    and not has_hirings_after_suspension
                ):
                    context["approval_deletion_form_url"] = "https://tally.so/r/3je84Q?" + urllib.parse.urlencode(
                        {
                            "siaeID": self.siae.pk,
                            "nomSIAE": self.siae.display_name,
                            "prenomemployeur": self.request.user.first_name,
                            "nomemployeur": self.request.user.last_name,
                            "emailemployeur": self.request.user.email,
                            "userID": self.request.user.pk,
                            "numPASS": approval.number_with_spaces,
                            "prenomsalarie": approval.user.first_name,
                            "nomsalarie": approval.user.last_name,
                        }
                    )
                    break

        if approval.remainder.days < 90 and self.request.user.is_employer:
            context["link_immersion_facile"] = immersion_search_url(approval.user)
            context["approval_expired"] = not approval.is_in_progress

        context["all_job_applications"] = (
            JobApplication.objects.filter(
                job_seeker=approval.user,
                to_company=self.siae,
            )
            .select_related("sender", "to_company")
            .prefetch_related("selected_jobs")
        )
        return context
