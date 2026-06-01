from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

from itou.recommendations import services
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import readonly_view
from itou.www.recommendations.enums import BeneficiaryOrder
from itou.www.recommendations.forms import BeneficiaryListFilterForm
from itou.www.recommendations.views.common import is_recommendations_advisor


@readonly_view
@check_request(is_recommendations_advisor)
def list_beneficiaries(request, template_name="recommendations/list.html"):
    try:
        order = BeneficiaryOrder(request.GET.get("order"))
    except ValueError:
        order = BeneficiaryOrder.FULL_NAME_ASC

    beneficiaries_qs = services.get_beneficiaries_qs(user=request.user, organization=request.current_organization)

    filters_form = BeneficiaryListFilterForm(data=request.GET or None, beneficiaries_qs=beneficiaries_qs)
    selected_kinds = []
    selected_beneficiary = None
    filters_counter = 0
    if filters_form.is_valid():
        selected_kinds = filters_form.cleaned_data.get("profile_kinds") or []
        selected_beneficiary = filters_form.cleaned_data.get("beneficiary")
        filters_counter = sum(bool(filters_form.cleaned_data.get(field.name)) for field in filters_form)

    beneficiaries = services.get_beneficiaries_for_user(
        user=request.user,
        organization=request.current_organization,
        order=order,
        profile_kinds=selected_kinds,
        beneficiary=selected_beneficiary,
    )

    beneficiaries_page = pager(beneficiaries, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_LARGE)
    for beneficiary in beneficiaries_page:
        beneficiary.flags = services.profile_flags(beneficiary)

    context = {
        "filters_counter": filters_counter,
        "filters_form": filters_form,
        "beneficiaries_page": beneficiaries_page,
        "paginator": beneficiaries_page.paginator,
        "order": order,
        "BeneficiaryOrder": BeneficiaryOrder,
    }

    if request.htmx:
        template_name = "recommendations/includes/list_results.html"
    return render(request, template_name, context)


@readonly_view
@check_request(is_recommendations_advisor)
def beneficiary_autocomplete(request):
    beneficiaries_list = services.beneficiary_autocomplete_search(
        user=request.user,
        organization=request.current_organization,
        term=request.GET.get("term", ""),
    )
    return JsonResponse(
        {
            "results": [
                {
                    "id": beneficiary.pk,
                    "text": beneficiary.get_inverted_full_name(),
                }
                for beneficiary in beneficiaries_list
            ]
        },
        safe=False,
    )
