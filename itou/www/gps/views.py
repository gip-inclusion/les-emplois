from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse, reverse_lazy

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.utils.decorators import settings_protected_view
from itou.utils.urls import get_safe_url
from itou.www.gps.forms import GpsUserSearchForm


@login_required
@settings_protected_view("GPS_ENABLED")
@user_passes_test(
    lambda u: not u.is_job_seeker,
    login_url=reverse_lazy("dashboard:index"),
    redirect_field_name=None,
)
def my_groups(request, template_name="gps/my_groups.html"):
    current_user = request.user

    memberships = (
        FollowUpGroupMembership.objects.filter(member=current_user)
        .filter(is_active=True)
        .annotate(nb_members=Count("follow_up_group__members"))
        .select_related("follow_up_group", "follow_up_group__beneficiary", "member")
        .prefetch_related("follow_up_group__members")
    )

    breadcrumbs = {
        "Mes bénéficiaires": reverse("gps:my_groups"),
    }

    context = {
        "breadcrumbs": breadcrumbs,
        "memberships": memberships,
    }

    return render(request, template_name, context)


@login_required
@settings_protected_view("GPS_ENABLED")
@user_passes_test(
    lambda u: not u.is_job_seeker,
    login_url=reverse_lazy("dashboard:index"),
    redirect_field_name=None,
)
def join_group(request, template_name="gps/join_group.html"):
    form = GpsUserSearchForm(request.current_organization, data=request.POST or None)

    my_groups_url = reverse("gps:my_groups")
    back_url = get_safe_url(request, "back_url", my_groups_url)

    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user"]
        is_referent = form.cleaned_data["is_referent"]

        FollowUpGroup.objects.follow_beneficiary(beneficiary=user, user=request.user, is_referent=is_referent)

        return HttpResponseRedirect(my_groups_url)

    breadcrumbs = {
        "Mes bénéficiaires": my_groups_url,
        "Ajouter un bénéficiaire": reverse("gps:join_group"),
    }

    context = {"breadcrumbs": breadcrumbs, "form": form, "reset_url": back_url}

    return render(request, template_name, context)


@login_required
@settings_protected_view("GPS_ENABLED")
@user_passes_test(
    lambda u: not u.is_job_seeker,
    login_url=reverse_lazy("dashboard:index"),
    redirect_field_name=None,
)
def leave_group(request, group_id):
    membership = (
        FollowUpGroupMembership.objects.filter(member=request.user).filter(follow_up_group__id=group_id).first()
    )

    if membership:
        membership.is_active = False
        membership.save()

    return HttpResponseRedirect(reverse("gps:my_groups"))


@login_required
@settings_protected_view("GPS_ENABLED")
@user_passes_test(
    lambda u: not u.is_job_seeker,
    login_url=reverse_lazy("dashboard:index"),
    redirect_field_name=None,
)
def toggle_referent(request, group_id):
    membership = (
        FollowUpGroupMembership.objects.filter(member=request.user).filter(follow_up_group__id=group_id).first()
    )

    if membership:
        membership.is_referent = not membership.is_referent
        membership.save()

    return HttpResponseRedirect(reverse("gps:my_groups"))
