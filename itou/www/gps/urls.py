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
    # FIXME Old view to delete in a few days
    path("details/<uuid:public_id>", views.user_details, name="user_details"),
    path(
        "display/<int:group_id>/<uuid:target_participant_public_id>/<str:mode>",
        views.display_contact_info,
        name="display_contact_info",
    ),
    # Backward compatibility - used in bizdev mailing
    path("", RedirectView.as_view(url=reverse_lazy("gps:group_list"), permanent=True)),
    path("groups", RedirectView.as_view(url=reverse_lazy("gps:group_list"), permanent=True)),
]
