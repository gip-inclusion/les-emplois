from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Exists, OuterRef, Prefetch
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView, UpdateView

from itou.gps.grist import log_contact_info_display
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_user
from itou.utils.pagination import pager
from itou.utils.session import SessionNamespace
from itou.utils.templatetags.str_filters import mask_unless
from itou.utils.urls import add_url_params, get_absolute_url, get_safe_url
from itou.www.gps.enums import Channel
from itou.www.gps.forms import (
    FollowUpGroupMembershipForm,
    JobSeekerSearchByNameEmailForm,
    JobSeekersFollowedByCoworkerSearchForm,
    JoinGroupChannelForm,
    MembershipsFiltersForm,
)
from itou.www.gps.utils import add_beneficiary, get_all_coworkers, send_slack_message_for_gps
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from itou.www.job_seekers_views.forms import CheckJobSeekerNirForm


def is_allowed_to_use_gps(user):
    return user.is_employer or user.is_prescriber


def is_allowed_to_use_gps_advanced_features(user):
    return user.is_employer or user.is_prescriber_with_authorized_org


def show_gps_as_a_nav_entry(request):
    return getattr(request.current_organization, "department", None) in settings.GPS_NAV_ENTRY_DEPARTMENTS


@check_user(is_allowed_to_use_gps)
def group_list(request, current, template_name="gps/group_list.html"):
    qs = FollowUpGroupMembership.objects.filter(member=request.user, is_active=True)

    if current:
        qs = qs.filter(ended_at=None)
    else:
        qs = qs.exclude(ended_at=None)

    memberships = (
        qs.annotate(nb_members=Count("follow_up_group__members"))
        .order_by("-created_at")
        .select_related("follow_up_group", "follow_up_group__beneficiary", "member")
        .prefetch_related(
            Prefetch(
                "follow_up_group__memberships",
                queryset=FollowUpGroupMembership.objects.filter(is_referent=True).select_related("member")[:1],
                to_attr="referent",
            ),
        )
    )
    filters_form = MembershipsFiltersForm(
        memberships_qs=memberships,
        data=request.GET or None,
        request_user=request.user,
    )

    if filters_form.is_valid():
        memberships = filters_form.filter()

    memberships_page = pager(memberships, request.GET.get("page"), items_per_page=50)
    for membership in memberships_page:
        membership.user_can_view_personal_information = request.user.can_view_personal_information(
            membership.follow_up_group.beneficiary
        )

    context = {
        "filters_form": filters_form,
        "memberships_page": memberships_page,
        "active_memberships": current,
    }

    return render(request, "gps/includes/memberships_results.html" if request.htmx else template_name, context)


class GroupDetailsMixin(LoginRequiredMixin):
    # Don't use UserPassesTestMixin because we need the kwargs
    def setup(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if not is_allowed_to_use_gps(request.user):
                raise PermissionDenied("Votre utilisateur n'est pas autorisé à accéder à ces informations.")
            self.group = get_object_or_404(FollowUpGroup.objects.select_related("beneficiary"), pk=kwargs["group_id"])
            self.membership = get_object_or_404(
                FollowUpGroupMembership.objects.filter(is_active=True), follow_up_group=self.group, member=request.user
            )
        super().setup(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        back_url = get_safe_url(self.request, "back_url", fallback_url=reverse_lazy("gps:group_list"))
        return context | {
            "back_url": back_url,
            "group": self.group,
            "can_view_personal_information": self.request.user.can_view_personal_information(self.group.beneficiary),
        }


class GroupMembershipsView(GroupDetailsMixin, TemplateView):
    template_name = "gps/group_memberships.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        memberships = (
            FollowUpGroupMembership.objects.with_members_organizations_names()
            .filter(follow_up_group=self.group)
            .filter(is_active=True)
            .order_by("-created_at")
            .select_related("member")
        )

        request_new_participant_form_url = add_url_params(
            "https://formulaires.gps.inclusion.gouv.fr/ajouter-intervenant?",
            {
                "user_name": self.request.user.get_full_name(),
                "user_id": self.request.user.pk,
                "user_email": self.request.user.email,
                "user_organization_name": getattr(self.request.current_organization, "display_name", ""),
                "user_organization_id": getattr(self.request.current_organization, "pk", ""),
                "user_type": self.request.user.kind,
                "beneficiary_name": self.group.beneficiary.get_full_name(),
                "beneficiary_id": self.group.beneficiary.pk,
                "beneficiary_email": self.group.beneficiary.email,
                "success_url": self.request.build_absolute_uri(),
            },
        )

        context = context | {
            "gps_memberships": memberships,
            "is_referent": self.membership.is_referent,
            "matomo_custom_title": "Profil GPS - participants",
            "request_new_participant_form_url": request_new_participant_form_url,
            "active_tab": "memberships",
        }

        return context


class GroupBeneficiaryView(GroupDetailsMixin, TemplateView):
    template_name = "gps/group_beneficiary.html"

    def get_live_department_codes(self):
        """For the initial release only some departments have the feature"""
        return [
            "30",  # Le Gard
            "55",  # La Meuse
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        org_department = getattr(self.request.current_organization, "department", None)
        matomo_option = org_department if org_department in self.get_live_department_codes() else None

        context = context | {
            "can_see_diagnosis": is_allowed_to_use_gps_advanced_features(self.request.user),
            "matomo_custom_title": "Profil GPS - bénéficiaire",
            "render_advisor_matomo_option": matomo_option,
            "matomo_option": f"coordonnees-conseiller-{matomo_option or 'ailleurs'}",
            "active_tab": "beneficiary",
            "can_edit_personal_information": self.request.user.can_edit_personal_information(self.group.beneficiary),
        }

        return context


class GroupContributionView(GroupDetailsMixin, TemplateView):
    template_name = "gps/group_contribution.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context | {
            "membership": self.membership,
            "matomo_custom_title": "Profil GPS - mon intervention",
            "active_tab": "contribution",
        }


class GroupEditionView(GroupDetailsMixin, UpdateView):
    template_name = "gps/group_edition.html"
    form_class = FollowUpGroupMembershipForm
    model = FollowUpGroupMembership

    def get_object(self, queryset=None):
        return self.membership

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "matomo_custom_title": "Profil GPS - mon intervention",
        }

    def get_success_url(self):
        return reverse("gps:group_contribution", args=(self.group.pk,))


@check_user(is_allowed_to_use_gps)
def user_details(request, public_id):
    membership = get_object_or_404(
        FollowUpGroupMembership.objects.select_related("follow_up_group"),
        follow_up_group__beneficiary__public_id=public_id,
        member=request.user,
        is_active=True,
    )

    return HttpResponseRedirect(reverse("gps:group_memberships", args=(membership.follow_up_group.pk,)))


@require_POST
@check_user(is_allowed_to_use_gps)
def display_contact_info(request, group_id, target_participant_public_id, mode):
    template_name = {
        "email": "gps/includes/member_email.html",
        "phone": "gps/includes/member_phone.html",
    }.get(mode, None)
    if not template_name:
        raise ValueError("Invalid mode: %s", mode)

    follow_up_group = get_object_or_404(FollowUpGroup.objects.filter(members=request.user), pk=group_id)
    target_participant = get_object_or_404(
        User.objects.filter(follow_up_groups__follow_up_group_id=group_id),
        public_id=target_participant_public_id,
    )
    log_contact_info_display(request.user, follow_up_group, target_participant, mode)
    return render(request, template_name, {"member": target_participant})


@check_user(is_allowed_to_use_gps)
def join_group(request, template_name="gps/join_group.html"):
    urls = {
        Channel.FROM_COWORKER: reverse("gps:join_group_from_coworker"),
        Channel.FROM_NIR: reverse("gps:join_group_from_nir"),
        Channel.FROM_NAME_EMAIL: reverse("gps:join_group_from_name_and_email"),
    }
    if request.current_organization is None:
        return HttpResponseRedirect(urls[Channel.FROM_NAME_EMAIL])

    form = JoinGroupChannelForm(data=request.POST or None)
    if request.POST and form.is_valid():
        return HttpResponseRedirect(urls[form.cleaned_data["channel"]])

    context = {
        "back_url": get_safe_url(request, "back_url", fallback_url=reverse_lazy("gps:group_list")),
        "can_use_gps_advanced_features": is_allowed_to_use_gps_advanced_features(request.user),
        "Channel": Channel,
    }
    return render(request, template_name, context)


@check_user(is_allowed_to_use_gps)
def join_group_from_coworker(request, template_name="gps/join_group_from_coworker.html"):
    if request.current_organization is None:
        raise PermissionDenied("Il faut une organisation ou une structure pour accéder à cette page")

    form = JobSeekersFollowedByCoworkerSearchForm(data=request.POST or None, organizations=request.organizations)

    if request.method == "POST" and form.is_valid():
        add_beneficiary(request, form.job_seeker)
        return HttpResponseRedirect(reverse("gps:group_list"))

    context = {
        "form": form,
        "reset_url": get_safe_url(request, "back_url", fallback_url=reverse("gps:join_group")),
    }

    return render(request, template_name, context)


@check_user(is_allowed_to_use_gps_advanced_features)
def join_group_from_nir(request, template_name="gps/join_group_from_nir.html"):
    form = CheckJobSeekerNirForm(data=request.POST or None, is_gps=True)
    context = {
        "form": form,
        "reset_url": get_safe_url(request, "back_url", fallback_url=reverse("gps:join_group")),
        "job_seeker": None,
        "preview_mode": False,
    }

    if request.method == "POST" and form.is_valid():
        job_seeker = form.get_job_seeker()

        if job_seeker is None:
            # Maybe plug into GetOrCreateJobSeekerStartView
            data = {
                "config": {
                    "tunnel": "gps",
                    "from_url": request.get_full_path(),
                    "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
                },
                "profile": {"nir": form.cleaned_data["nir"]},
            }
            job_seeker_session = SessionNamespace.create_uuid_namespace(request.session, data)
            return HttpResponseRedirect(
                reverse(
                    "job_seekers_views:search_by_email_for_sender",
                    kwargs={"session_uuid": job_seeker_session.name},
                )
            )

        if form.data.get("confirm"):
            add_beneficiary(request, job_seeker)
            return HttpResponseRedirect(reverse("gps:group_list"))

        context |= {
            # Ask the sender to confirm the NIR we found is associated to the correct user
            "preview_mode": job_seeker and bool(form.data.get("preview")),
            "job_seeker": job_seeker,
            "nir_not_found": job_seeker is None,
        }

    return render(request, template_name, context)


@check_user(is_allowed_to_use_gps)
def join_group_from_name_and_email(request, template_name="gps/join_group_from_name_and_email.html"):
    form = JobSeekerSearchByNameEmailForm(data=request.POST or None)
    context = {
        "form": form,
        "reset_url": get_safe_url(request, "back_url", fallback_url=reverse("gps:join_group")),
        "job_seeker": None,
        "email_only_match": False,
        "preview_mode": False,
    }

    if request.method == "POST" and form.is_valid():
        job_seeker = (
            User.objects.filter(
                kind=UserKind.JOB_SEEKER,
                first_name__iexact=form.cleaned_data["first_name"],
                last_name__iexact=form.cleaned_data["last_name"],
                email=form.cleaned_data["email"],
            )
            .select_related("jobseeker_profile")
            .first()
        )

        if job_seeker is None:
            job_seeker_email_match = User.objects.filter(
                kind=UserKind.JOB_SEEKER, email=form.cleaned_data["email"]
            ).first()
            if job_seeker_email_match:
                context["email_only_match"] = True
                if is_allowed_to_use_gps_advanced_features(request.user):
                    # slight change in modal wording
                    job_seeker = job_seeker_email_match
                else:
                    form.add_error(
                        "__all__",
                        mark_safe(
                            "<strong>Veuillez vérifier le nom ou l’e-mail.</strong><br>"
                            "Un compte bénéficiaire avec un nom différent existe déjà pour cette adresse e-mail."
                        ),
                    )

            else:
                # Maybe plug into GetOrCreateJobSeekerStartView
                data = {
                    "config": {
                        "tunnel": "gps",
                        "from_url": request.get_full_path(),
                        "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
                    },
                    "user": form.cleaned_data,
                }
                job_seeker_session = SessionNamespace.create_uuid_namespace(request.session, data)
                return HttpResponseRedirect(
                    reverse(
                        "job_seekers_views:create_job_seeker_step_1_for_sender",
                        kwargs={"session_uuid": job_seeker_session.name},
                    )
                )

        # For authorized prescribers + employers
        if form.data.get("confirm") and is_allowed_to_use_gps_advanced_features(request.user):
            add_beneficiary(request, job_seeker)
            return HttpResponseRedirect(reverse("gps:group_list"))

        # For non authorized prescribers
        if form.data.get("ask"):
            job_seeker_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(job_seeker.pk,)))
            user_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(request.user.pk,)))
            membership = add_beneficiary(request, job_seeker, is_active=False)
            membership_url = get_absolute_url(
                reverse("admin:gps_followupgroupmembership_change", args=(membership.pk,))
            )
            send_slack_message_for_gps(
                f":gemini: Demande d’ajout <{user_admin_url}|{request.user.get_full_name()}> "
                f"veut suivre <{job_seeker_admin_url}|{mask_unless(job_seeker.get_full_name(), False)}> "
                f"(<{membership_url}|relation>)."
            )
            return HttpResponseRedirect(reverse("gps:group_list"))

        context |= {
            # Ask the sender to confirm the found user is correct
            "preview_mode": job_seeker and bool(form.data.get("preview")),
            "job_seeker": job_seeker,
            "can_use_gps_advanced_features": is_allowed_to_use_gps_advanced_features(request.user),
        }

    return render(request, template_name, context)


@check_user(is_allowed_to_use_gps)
def beneficiaries_autocomplete(request):
    """
    Returns JSON data compliant with Select2
    """
    if request.current_organization is None:
        raise PermissionDenied("Il faut une organisation ou une structure pour accéder à cette page")

    term = request.GET.get("term", "").strip()
    users = []

    if term:
        all_coworkers = get_all_coworkers(request.organizations)
        users_qs = (
            User.objects.search_by_full_name(term)
            .filter(kind=UserKind.JOB_SEEKER)
            .filter(
                Exists(
                    FollowUpGroupMembership.objects.filter(
                        follow_up_group__beneficiary_id=OuterRef("pk"),
                        member__in=all_coworkers.values("pk"),
                    )
                )
            )
        )

        def format_data(user):
            data = {
                "id": user.pk,
                "title": "",
                "name": mask_unless(user.get_full_name(), predicate=request.user.can_view_personal_information(user)),
                "birthdate": "",
            }
            if user.title:
                # only add a . after M, not Mme
                data["title"] = (
                    f"{user.title.capitalize()}."[:3] if request.user.can_view_personal_information(user) else ""
                )
            if getattr(user.jobseeker_profile, "birthdate", None):
                data["birthdate"] = (
                    user.jobseeker_profile.birthdate.strftime("%d/%m/%Y")
                    if request.user.can_view_personal_information(user)
                    else ""
                )
            return data

        users = [format_data(user) for user in users_qs[:10]]

    return JsonResponse({"results": users})
