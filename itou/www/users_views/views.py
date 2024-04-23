from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView

from itou.gps.models import FollowUpGroupMembership
from itou.users.models import User
from itou.www.approvals_views.views import ApprovalListView


class UserDetailsView(LoginRequiredMixin, DetailView):
    model = User
    queryset = User.objects.select_related("follow_up_group").prefetch_related("follow_up_group__memberships")
    template_name = "users/details.html"
    slug_field = "public_id"
    slug_url_kwarg = "public_id"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["gps_memberships"] = (
            FollowUpGroupMembership.objects.filter(follow_up_group=context["object"].follow_up_group)
            .filter(is_active=True)
            .select_related("follow_up_group", "member")
        )
        return context
        # context = super().get_context_data(**kwargs)
        # approval = self.object
        # job_application = self.get_job_application(self.object)

        # context["can_view_personal_information"] = True  # SIAE members have access to personal info
        # context["can_edit_personal_information"] = self.request.user.can_edit_personal_information(approval.user)
        # context["approval_can_be_suspended_by_siae"] = approval.can_be_suspended_by_siae(self.siae)
        # context["hire_by_other_siae"] = not approval.user.last_hire_was_made_by_company(self.siae)
        # context["approval_can_be_prolonged"] = approval.can_be_prolonged
        # context["job_application"] = job_application
        # context["hiring_pending"] = job_application and job_application.is_pending
        # context["matomo_custom_title"] = "Profil salarié"
        # context["eligibility_diagnosis"] = job_application and job_application.get_eligibility_diagnosis()

        # if approval.is_in_progress:
        #     for suspension in approval.suspensions_by_start_date_asc:
        #         if suspension.is_in_progress:
        #             suspension_duration = date.today() - suspension.start_at
        #             has_hirings_after_suspension = False
        #         else:
        #             suspension_duration = suspension.duration
        #             has_hirings_after_suspension = (
        #                 approval.jobapplication_set.accepted()

    # .filter(hiring_start_at__gte=suspension.end_at).exists()
    #             )

    #         if (
    #             suspension_duration > SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE
    #             and not has_hirings_after_suspension
    #         ):
    #             context["approval_deletion_form_url"] = "https://tally.so/r/3je84Q?" + urllib.parse.urlencode(
    #                 {
    #                     "siaeID": self.siae.pk,
    #                     "nomSIAE": self.siae.display_name,
    #                     "prenomemployeur": self.request.user.first_name,
    #                     "nomemployeur": self.request.user.last_name,
    #                     "emailemployeur": self.request.user.email,
    #                     "userID": self.request.user.pk,
    #                     "numPASS": approval.number_with_spaces,
    #                     "prenomsalarie": approval.user.first_name,
    #                     "nomsalarie": approval.user.last_name,
    #                 }
    #             )
    #             break

    # context["all_job_applications"] = (
    #     JobApplication.objects.filter(
    #         job_seeker=approval.user,
    #         to_company=self.siae,
    #     )
    #     .select_related("sender")
    #     .prefetch_related("selected_jobs")
    # )
    # return context


class UserListView(ApprovalListView):
    # Use the same logic as Approval view but change the details link.
    # This is just for demo purposes as long as the GPS app is not ready to use.
    template_name = "users/list.html"
