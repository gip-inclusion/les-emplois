from django import forms
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from itou.common_apps.address.forms import JobSeekerAddressForm
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.perms.utils import can_view_personal_information
from itou.utils.readonly import http_methods, readonly_view
from itou.utils.views import with_triggers_context
from itou.www.next_steps_views import engine
from itou.www.next_steps_views.access import can_view_next_steps
from itou.www.next_steps_views.actions import (
    Group,
    describe_job_seekers,
    done_today,
    expected_actions,
    group_actions,
    next_action,
)
from itou.www.next_steps_views.journeys import JOURNEYS


def _journeys_media(request):
    """Scripts of the forms the journeys may show, loaded with the page: htmx does not run swapped scripts."""
    media = forms.Media()
    if request.from_employer:
        for field in JobSeekerAddressForm.base_fields.values():
            media += field.widget.media
    return media


@readonly_view
def todo(request, template_name="next_steps/todo.html"):
    """« À faire »: the actions expected from the signed-in professional, by urgency."""
    if not can_view_next_steps(request):
        raise Http404

    actions = expected_actions(request)
    describe_job_seekers(actions, lambda job_seeker: can_view_personal_information(request, job_seeker))
    done = done_today(request)
    describe_job_seekers(done, lambda job_seeker: can_view_personal_information(request, job_seeker))
    context = {
        "groups": group_actions(actions),
        "pressing_count": sum(action.group != Group.WATCH for action in actions),
        "done_today": done,
        "journeys_media": _journeys_media(request),
        "matomo_custom_title": "Prochaines étapes : à faire",
    }
    return render(request, template_name, context)


@http_methods(db_readonly=["GET", "HEAD"], db_write=["POST"])
@with_triggers_context
def journey(request, kind, pk):
    """A guided journey: in the side drawer when loaded by htmx, an ordinary page otherwise."""
    if not can_view_next_steps(request) or kind not in JOURNEYS:
        raise Http404
    current_journey = JOURNEYS[kind](request, pk)
    context, completed = engine.run(current_journey, request.POST if request.method == "POST" else None)
    context |= {
        "journey_url": request.path,
        "in_drawer": bool(request.htmx),
        "can_view_name": can_view_personal_information(request, current_journey.job_seeker),
        "matomo_custom_title": f"Prochaines étapes : parcours {kind}",
        "journeys_media": _journeys_media(request),
        "next_action": None,
        "remaining": None,
    }
    if completed:
        # Keep the momentum: what remains today, and the next action to run, right from the confirmation.
        actions = expected_actions(request)
        describe_job_seekers(actions, lambda job_seeker: can_view_personal_information(request, job_seeker))
        context["remaining"] = sum(action.group != Group.WATCH for action in actions)
        context["next_action"] = next_action(actions)
    template_name = "next_steps/journeys/journey.html" if request.htmx else "next_steps/journeys/page.html"
    response = render(request, template_name, context)
    if completed:
        # Pages listening to this event reload their actions.
        response["HX-Trigger"] = "nextStepsChanged"
    return response


def _job_seeker_or_404(request, public_id):
    if not can_view_next_steps(request):
        raise Http404
    return get_object_or_404(
        User.objects.select_related("jobseeker_profile"), kind=UserKind.JOB_SEEKER, public_id=public_id
    )
