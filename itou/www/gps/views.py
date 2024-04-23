from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.www.gps.forms import GpsUserSearchForm


@login_required
def my_groups(request, template_name="gps/my_groups.html"):

    current_user = request.user

    memberships = (
        FollowUpGroupMembership.objects.filter(member=current_user)
        .filter(is_active=True)
        .select_related("follow_up_group", "follow_up_group__beneficiary", "member")
        .prefetch_related("follow_up_group__members")
    )

    breadcrumbs = {
        "Mes groupes de suivi": reverse("gps:my_groups"),
    }

    context = {
        "breadcrumbs": breadcrumbs,
        "memberships": memberships,
    }

    return render(request, template_name, context)


@login_required
def join_group(request, template_name="gps/join_group.html"):

    form = GpsUserSearchForm(data=request.POST or None)

    my_groups_url = reverse("gps:my_groups")

    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user"]
        is_referent = form.cleaned_data["is_referent"]

        group = user.follow_up_group if (hasattr(user, "follow_up_group")) else None

        if group is None:
            group = FollowUpGroup.objects.create(beneficiary=user)

        group.members.add(request.user, through_defaults={"creator": request.user, "is_referent": is_referent})

        return HttpResponseRedirect(my_groups_url)

    breadcrumbs = {
        "Mes groupes de suivi": my_groups_url,
        "Rejoindre un groupe de suivi": reverse("gps:join_group"),
    }

    context = {"breadcrumbs": breadcrumbs, "form": form, "reset_url": my_groups_url}

    return render(request, template_name, context)
