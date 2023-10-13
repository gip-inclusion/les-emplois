from django.urls import path

from itou.www.invitations_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "invitations_views"

urlpatterns = [
    path("invite_labor_inspector", views.invite_labor_inspector, name="invite_labor_inspector"),
    path("invite_prescriber_with_org", views.invite_prescriber_with_org, name="invite_prescriber_with_org"),
    path("invite_employer", views.invite_employer, name="invite_employer"),
    path("<str:invitation_type>/<uuid:invitation_id>/new_user", views.new_user, name="new_user"),
    path("<uuid:invitation_id>/join_institution", views.join_institution, name="join_institution"),
    path(
        "<uuid:invitation_id>/join_prescriber_organization",
        views.join_prescriber_organization,
        name="join_prescriber_organization",
    ),
    path("<uuid:invitation_id>/join_siae", views.join_siae, name="join_siae"),
]
