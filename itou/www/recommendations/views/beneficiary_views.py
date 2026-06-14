from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from itou.recommendations import services
from itou.utils.auth import check_request
from itou.utils.readonly import readonly_view
from itou.utils.urls import get_safe_url
from itou.www.recommendations.forms import RecommendationsFilterForm
from itou.www.recommendations.views.common import is_recommendations_advisor


def _get_beneficiary_or_404(request, public_id):
    beneficiary = services.get_beneficiary_for_user(
        public_id=public_id,
        user=request.user,
        organization=request.current_organization,
    )
    if beneficiary is None:
        raise Http404
    return beneficiary


def _profile_context(request, public_id, active_tab):
    beneficiary = _get_beneficiary_or_404(request, public_id)
    flags = services.profile_flags(beneficiary)
    return {
        "beneficiary": beneficiary,
        "flags": flags,
        "criteria_labels": services.profile_criteria_labels(flags),
        "active_tab": active_tab,
        "back_url": get_safe_url(request, "back_url", fallback_url=reverse("recommendations:beneficiary_list")),
        "france_travail_id": beneficiary.france_travail_id,
        # FIXME lalba: hardcoded
        "modality_classes": "bg-accent-03 text-primary",
        "modality_label": "Intensif",
        "modality_duration": "Depuis + 5 mois",
    }


@readonly_view
@check_request(is_recommendations_advisor)
def beneficiary_profile(request, public_id, template_name="recommendations/beneficiary_profile.html"):
    context = _profile_context(request, public_id, "profile")
    context |= {
        "matomo_custom_title": "Profil bénéficiaire",
        "diagnostic": services.beneficiary_diagnostic_for(beneficiary=context["beneficiary"]),
        # FIXME lalba: hardcoded
        "referring_structure": "Lille Avenir (PLIE)",
        "referring_advisor": "Sophie Dufour — Lille Avenir",
    }
    return render(request, template_name, context)


@readonly_view
@check_request(is_recommendations_advisor)
def beneficiary_actions(request, public_id, template_name="recommendations/beneficiary_actions.html"):
    context = _profile_context(request, public_id, "actions")
    filters_form = RecommendationsFilterForm(data=request.GET or None)
    context["filters_form"] = filters_form
    context["filters_counter"] = (
        sum(1 for value in filters_form.cleaned_data.values() if value) if filters_form.is_valid() else 0
    )
    context["recommendations"] = services.recommendations_for(beneficiary=context["beneficiary"])
    context["recommendations_count"] = sum(len(item["providers"]) for item in context["recommendations"])
    context["map_points"] = services.map_points_for(context["recommendations"])
    if request.htmx:
        template_name += "#actions-results"
    return render(request, template_name, context)


@require_POST
@check_request(is_recommendations_advisor)
def mobilise(request, public_id):
    # FIXME lalba: no-op pour le moment, à compléter une fois le cahier des charges précisé
    _get_beneficiary_or_404(request, public_id)
    if request.htmx:
        return render(request, "recommendations/includes/recommendation_card.html#mobilise-success")
    messages.success(request, "Recommandation enregistrée.")
    return redirect("recommendations:beneficiary_actions", public_id=public_id)
