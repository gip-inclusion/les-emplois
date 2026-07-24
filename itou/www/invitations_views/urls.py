from django.urls import path

from itou.www.invitations_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "invitations_views"

urlpatterns = [
    path("invite_labor_inspector", views.InviteLaborInspectorView.as_view(), name="invite_labor_inspector"),
    path("invite_prescriber_with_org", views.InvitePrescriberView.as_view(), name="invite_prescriber_with_org"),
    path("invite_employer", views.InviteEmployerView.as_view(), name="invite_employer"),
    path("<str:invitation_type>/<uuid:invitation_id>/new_user", views.new_user, name="new_user"),
    path("<str:invitation_type>/<uuid:invitation_id>/join", views.join, name="join"),
]
