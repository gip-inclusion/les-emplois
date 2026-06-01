from django.urls import path

from itou.www.recommendations.views import beneficiary_views, list_views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "recommendations"

urlpatterns = [
    path("list", list_views.list_beneficiaries, name="beneficiary_list"),
    path("<uuid:public_id>/profile", beneficiary_views.beneficiary_profile, name="beneficiary_profile"),
    path("<uuid:public_id>/results", beneficiary_views.beneficiary_actions, name="beneficiary_actions"),
    path("<uuid:public_id>/mobilise", beneficiary_views.mobilise, name="mobilise"),
    path("autocomplete/beneficiary", list_views.beneficiary_autocomplete, name="beneficiary_autocomplete"),
]
