from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Exists, OuterRef, Prefetch
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView, UpdateView

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.perms.utils import can_edit_personal_information, can_view_personal_information
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
from itou.www.gps.utils import (
    add_beneficiary,
    get_all_coworkers,
    is_gps_authorized,
    logger,
    send_slack_message_for_gps,
)
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from itou.www.job_seekers_views.forms import CheckJobSeekerNirForm


def is_allowed_to_use_gps(request):
    return request.user.is_employer or request.user.is_prescriber


def is_allowed_to_use_gps_advanced_features(request):
    return request.user.is_employer or request.from_authorized_prescriber or is_gps_authorized(request)


def show_gps_as_a_nav_entry(request):
    return getattr(request.current_organization, "department", None) in settings.GPS_NAV_ENTRY_DEPARTMENTS


@check_request(is_allowed_to_use_gps)
def group_list(request, current, template_name="gps/group_list.html"):
    logger.info(f"GPS visit_list_groups{'_old' if current is False else ''}")
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
                queryset=FollowUpGroupMembership.objects.filter(is_referent_certified=True).select_related("member")[
                    :1
                ],
                to_attr="referent",
            ),
        )
    )
    filters_form = MembershipsFiltersForm(
        memberships_qs=memberships,
        data=request.GET,
        request=request,
    )

    if filters_form.is_valid():
        memberships = filters_form.filter()

    memberships_page = pager(memberships, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_LARGE)
    for membership in memberships_page:
        membership.user_can_view_personal_information = (
            membership.can_view_personal_information
            or is_gps_authorized(request)
            or can_view_personal_information(request, membership.follow_up_group.beneficiary)
        )

    context = {
        "filters_form": filters_form,
        "memberships_page": memberships_page,
        "active_memberships": current,
    }

    return render(request, "gps/includes/memberships_results.html" if request.htmx else template_name, context)


class GroupDetailsMixin:
    # Don't use UserPassesTestMixin because we need the kwargs
    def setup(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if not is_allowed_to_use_gps(request):
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
            "can_view_personal_information": (
                self.membership.can_view_personal_information
                or is_gps_authorized(self.request)
                or can_view_personal_information(self.request, self.group.beneficiary)
            ),
            "can_print_page": True,
        }


class GroupMembershipsView(GroupDetailsMixin, TemplateView):
    template_name = "gps/group_memberships.html"

    def get(self, request, *args, **kwargs):
        logger.info("GPS visit_group_memberships", extra={"group": self.group.pk})
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        memberships = (
            FollowUpGroupMembership.objects.with_members_organizations_names()
            .filter(follow_up_group=self.group)
            .filter(is_active=True)
            .order_by("-is_referent_certified", "-created_at")
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
                "followupgroup_id": self.group.pk,
            },
        )

        context = context | {
            "gps_memberships": memberships,
            "matomo_custom_title": "Profil GPS - participants",
            "request_new_participant_form_url": request_new_participant_form_url,
            "active_tab": "memberships",
        }

        return context


class GroupBeneficiaryView(GroupDetailsMixin, TemplateView):
    template_name = "gps/group_beneficiary.html"

    def get(self, request, *args, **kwargs):
        logger.info("GPS visit_group_beneficiary", extra={"group": self.group.pk})
        return super().get(request, *args, **kwargs)

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
            "can_see_diagnosis": is_allowed_to_use_gps_advanced_features(self.request),
            "matomo_custom_title": "Profil GPS - bénéficiaire",
            "render_advisor_matomo_option": matomo_option,
            "matomo_option": f"coordonnees-conseiller-{matomo_option or 'ailleurs'}",
            "active_tab": "beneficiary",
            "can_edit_personal_information": can_edit_personal_information(self.request, self.group.beneficiary),
        }

        return context


class GroupContributionView(GroupDetailsMixin, TemplateView):
    template_name = "gps/group_contribution.html"

    def get(self, request, *args, **kwargs):
        logger.info("GPS visit_group_contribution", extra={"group": self.group.pk})
        return super().get(request, *args, **kwargs)

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

    def get(self, request, *args, **kwargs):
        logger.info("GPS visit_group_edition", extra={"group": self.group.pk})
        return super().get(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return self.membership

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {
            "matomo_custom_title": "Profil GPS - mon intervention",
            "can_print_page": False,
        }

    def get_success_url(self):
        return reverse("gps:group_contribution", args=(self.group.pk,))

    def form_valid(self, form):
        res = super().form_valid(form)
        changed_data = form.get_changed_data()
        base_extra = {"group": self.group.pk, "membership": self.membership.pk}
        if "reason" in changed_data:
            logger.info(
                "GPS changed_reason",
                extra=base_extra | {"length": len(form.cleaned_data["reason"])},
            )
        if "started_at" in changed_data:
            logger.info("GPS changed_start_date", extra=base_extra)
        if "ended_at" in changed_data:
            logger.info(
                "GPS changed_end_date",
                extra=base_extra | {"is_ongoing": not (form.cleaned_data["ended_at"])},
            )
        return res


def get_user_kind_display(user):
    if user.kind == UserKind.EMPLOYER:
        return "employeur"
    elif user.kind == UserKind.PRESCRIBER:
        if user.is_prescriber_with_authorized_org_memberships:
            return "prescripteur habilité"
        return "orienteur"
    raise ValueError("Invalid user kind: %s", user.kind)


@require_POST
@check_request(is_allowed_to_use_gps)
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
    are_colleagues = False
    if request.organizations and request.user.kind == target_participant.kind:
        org_ids = [org.pk for org in request.organizations]
        if request.user.is_employer:
            are_colleagues = target_participant.companymembership_set.filter(company__in=org_ids).exists()
        if request.user.is_prescriber:
            are_colleagues = target_participant.prescribermembership_set.filter(organization__in=org_ids).exists()

    logger.info(
        "GPS display_contact_information",
        extra={
            "group": group_id,
            "target_participant": target_participant.pk,
            "target_participant_type": get_user_kind_display(target_participant),
            "beneficiary": follow_up_group.beneficiary_id,
            "current_user": request.user.pk,
            "current_user_type": get_user_kind_display(request.user),
            "mode": mode,
            "are_colleagues": are_colleagues,
        },
    )
    return render(request, template_name, {"member": target_participant})


@require_POST
@check_request(is_allowed_to_use_gps)
def ask_access(request, group_id):
    follow_up_group = get_object_or_404(
        FollowUpGroup.objects.filter(members=request.user).select_related("beneficiary"),
        pk=group_id,
    )
    membership = get_object_or_404(
        follow_up_group.memberships,
        member=request.user,
    )
    if not membership.can_view_personal_information:
        beneficiary_admin_url = get_absolute_url(
            reverse("admin:users_user_change", args=(follow_up_group.beneficiary_id,))
        )
        user_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(request.user.pk,)))
        membership_url = get_absolute_url(reverse("admin:gps_followupgroupmembership_change", args=(membership.pk,)))
        send_slack_message_for_gps(
            f":mag: *Demande d’accès à la fiche*\n"
            f"<{user_admin_url}|{request.user.get_full_name()}> veut avoir accès aux informations de "
            f"<{beneficiary_admin_url}|{mask_unless(follow_up_group.beneficiary.get_full_name(), False)}> "
            f"(<{membership_url}|relation>)."
        )
        logger.info("GPS group_requested_full_access", extra={"group": group_id})
    return HttpResponse(
        '<button class="btn btn-sm btn-primary" disabled>Demander l’autorisation d’un administrateur</button>'
    )


@check_request(is_allowed_to_use_gps)
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

    logger.info("GPS visit_join_group_index")

    context = {
        "back_url": get_safe_url(request, "back_url", fallback_url=reverse_lazy("gps:group_list")),
        "can_use_gps_advanced_features": is_allowed_to_use_gps_advanced_features(request),
        "Channel": Channel,
    }
    return render(request, template_name, context)


@check_request(is_allowed_to_use_gps)
def join_group_from_coworker(request, template_name="gps/join_group_from_coworker.html"):
    if request.current_organization is None:
        raise PermissionDenied("Il faut une organisation ou une structure pour accéder à cette page")

    form = JobSeekersFollowedByCoworkerSearchForm(data=request.POST or None, organizations=request.organizations)

    if request.method == "POST" and form.is_valid():
        add_beneficiary(request, form.job_seeker, channel="coworker")
        return HttpResponseRedirect(reverse("gps:group_list"))

    logger.info("GPS visit_join_group_from_coworker")

    context = {
        "form": form,
        "reset_url": get_safe_url(request, "back_url", fallback_url=reverse("gps:join_group")),
    }

    return render(request, template_name, context)


@check_request(is_allowed_to_use_gps_advanced_features)
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
                },
                "profile": {"nir": form.cleaned_data["nir"]},
            }
            job_seeker_session = SessionNamespace.create(request.session, JobSeekerSessionKinds.GET_OR_CREATE, data)
            return HttpResponseRedirect(
                reverse(
                    "job_seekers_views:search_by_email_for_sender",
                    kwargs={"session_uuid": job_seeker_session.name},
                )
            )

        if form.data.get("confirm"):
            add_beneficiary(request, job_seeker, channel="nir")
            return HttpResponseRedirect(reverse("gps:group_list"))

        context |= {
            # Ask the sender to confirm the NIR we found is associated to the correct user
            "preview_mode": job_seeker and bool(form.data.get("preview")),
            "job_seeker": job_seeker,
            "nir_not_found": job_seeker is None,
        }

    logger.info("GPS visit_join_group_from_nir")

    return render(request, template_name, context)


@check_request(is_allowed_to_use_gps)
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
                if is_allowed_to_use_gps_advanced_features(request):
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
                    },
                    "user": form.cleaned_data,
                }
                job_seeker_session = SessionNamespace.create(
                    request.session, JobSeekerSessionKinds.GET_OR_CREATE, data
                )
                return HttpResponseRedirect(
                    reverse(
                        "job_seekers_views:create_job_seeker_step_1_for_sender",
                        kwargs={"session_uuid": job_seeker_session.name},
                    )
                )

        # For authorized prescribers + employers
        if form.data.get("confirm") and is_allowed_to_use_gps_advanced_features(request):
            add_beneficiary(request, job_seeker, channel="name_and_email")
            return HttpResponseRedirect(reverse("gps:group_list"))

        # For non authorized prescribers
        if form.data.get("ask"):
            job_seeker_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(job_seeker.pk,)))
            user_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(request.user.pk,)))
            membership = add_beneficiary(request, job_seeker, is_active=False, channel="name_and_email")
            membership_url = get_absolute_url(
                reverse("admin:gps_followupgroupmembership_change", args=(membership.pk,))
            )
            send_slack_message_for_gps(
                f":gemini: Demande d’ajout <{user_admin_url}|{request.user.get_full_name()}> "
                f"veut suivre <{job_seeker_admin_url}|{mask_unless(job_seeker.get_full_name(), False)}> "
                f"(<{membership_url}|relation>)."
            )
            return HttpResponseRedirect(reverse("gps:group_list"))

        logger.info("GPS visit_join_group_from_name_and_email")

        context |= {
            # Ask the sender to confirm the found user is correct
            "preview_mode": job_seeker and bool(form.data.get("preview")),
            "job_seeker": job_seeker,
            "can_use_gps_advanced_features": is_allowed_to_use_gps_advanced_features(request),
        }

    return render(request, template_name, context)


@check_request(is_allowed_to_use_gps)
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
            .annotate(
                membership_can_view_personal_information=Exists(
                    FollowUpGroupMembership.objects.filter(
                        follow_up_group__beneficiary_id=OuterRef("pk"),
                        member=request.user,
                        can_view_personal_information=True,
                    )
                )
            )
        )

        def format_data(user):
            data = {
                "id": user.pk,
                "title": "",
                "name": mask_unless(
                    user.get_full_name(),
                    predicate=(
                        user.membership_can_view_personal_information
                        or is_gps_authorized(request)
                        or can_view_personal_information(request, user)
                    ),
                ),
                "birthdate": "",
            }
            if user.title:
                # only add a . after M, not Mme
                data["title"] = (
                    f"{user.title.capitalize()}."[:3]
                    if user.membership_can_view_personal_information
                    or is_gps_authorized(request)
                    or can_view_personal_information(request, user)
                    else ""
                )
            if getattr(user.jobseeker_profile, "birthdate", None):
                data["birthdate"] = (
                    user.jobseeker_profile.birthdate.strftime("%d/%m/%Y")
                    if user.membership_can_view_personal_information
                    or is_gps_authorized(request)
                    or can_view_personal_information(request, user)
                    else ""
                )
            return data

        users = [format_data(user) for user in users_qs[:10]]

    return JsonResponse({"results": users})
