from django.urls import path, reverse_lazy
from django.views.generic import RedirectView

from itou.www.gps import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "gps"

urlpatterns = [
    path("groups/list", views.group_list, name="group_list", kwargs={"current": True}),
    path("groups/old/list", views.group_list, name="old_group_list", kwargs={"current": False}),
    path("groups/<int:group_id>/memberships", views.GroupMembershipsView.as_view(), name="group_memberships"),
    path("groups/<int:group_id>/beneficiary", views.GroupBeneficiaryView.as_view(), name="group_beneficiary"),
    path("groups/<int:group_id>/contribution", views.GroupContributionView.as_view(), name="group_contribution"),
    path("groups/<int:group_id>/edition", views.GroupEditionView.as_view(), name="group_edition"),
    path(
        "display/<int:group_id>/<uuid:target_participant_public_id>/<str:mode>",
        views.display_contact_info,
        name="display_contact_info",
    ),
    path("groups/<int:group_id>/ask-access", views.ask_access, name="ask_access"),
    path("groups/join", views.join_group, name="join_group"),
    path("groups/join/from-coworker", views.join_group_from_coworker, name="join_group_from_coworker"),
    path("groups/join/from-nir", views.join_group_from_nir, name="join_group_from_nir"),
    path("groups/join/from-name-email", views.join_group_from_name_and_email, name="join_group_from_name_and_email"),
    path("beneficiaries-autocomplete", views.beneficiaries_autocomplete, name="beneficiaries_autocomplete"),
    # Backward compatibility - used in bizdev mailing
    path("", RedirectView.as_view(url=reverse_lazy("gps:group_list"), permanent=True)),
    path("groups", RedirectView.as_view(url=reverse_lazy("gps:group_list"), permanent=True)),
]
