from django.urls import path

from itou.www.gps import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "gps"

urlpatterns = [
    path("groups/list", views.group_list, name="group_list"),
    path("groups/<int:group_id>/leave", views.leave_group, name="leave_group"),
    path("groups/<int:group_id>/toggle_referent", views.toggle_referent, name="toggle_referent"),
    path("details/<uuid:public_id>", views.UserDetailsView.as_view(), name="user_details"),
    path(
        "display/<int:group_id>/<uuid:target_participant_public_id>/<str:mode>",
        views.display_contact_info,
        name="display_contact_info",
    ),
]
