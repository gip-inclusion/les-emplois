from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Min
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.models import EvaluatedJobApplication, EvaluatedSiae, EvaluationCampaign
from itou.utils.perms.institution import get_current_institution_or_404
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.urls import get_safe_url
from itou.www.siae_evaluations_views.forms import SetChosenPercentForm


@login_required
def samples_selection(request, template_name="siae_evaluations/samples_selection.html"):
    institution = get_current_institution_or_404(request)
    evaluation_campaign = EvaluationCampaign.objects.first_active_campaign(institution)
    has_active_campaign = EvaluationCampaign.objects.has_active_campaign(institution)

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))

    form = SetChosenPercentForm(instance=evaluation_campaign, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.instance.percent_set_at = timezone.now()
        form.save()
        messages.success(
            request,
            f"Le pourcentage de sélection pour le contrôle a posteriori "
            f"a bien été enregistré ({form.cleaned_data['chosen_percent']}%).",
        )
        return HttpResponseRedirect(back_url)

    context = {
        "institution": institution,
        "evaluation_campaign": evaluation_campaign,
        "has_active_campaign": has_active_campaign,
        "min": evaluation_enums.EvaluationChosenPercent.MIN,
        "max": evaluation_enums.EvaluationChosenPercent.MAX,
        "back_url": back_url,
        "form": form,
    }
    return render(request, template_name, context)


@login_required
def siae_job_applications_list(request, template_name="siae_evaluations/siae_job_applications_list.html"):
    evaluations_asked_at = False
    evaluated_job_applications = False

    evaluated_siaes = (
        EvaluatedSiae.objects.for_siae(get_current_siae_or_404(request))
        .in_progress()
        .prefetch_related("evaluation_campaign")
    )

    if evaluated_siaes:
        evaluations_asked_at = evaluated_siaes.aggregate(date=Min("evaluation_campaign__evaluations_asked_at")).get(
            "date"
        )
        evaluated_job_applications = EvaluatedJobApplication.objects.filter(
            evaluated_siae__in=evaluated_siaes
        ).select_related("job_application", "job_application__job_seeker", "job_application__approval")

    back_url = get_safe_url(request, "back_url", fallback_url=reverse("dashboard:index"))
    context = {
        "evaluated_job_applications": evaluated_job_applications,
        "evaluations_asked_at": evaluations_asked_at,
        "back_url": back_url,
    }
    return render(request, template_name, context)
