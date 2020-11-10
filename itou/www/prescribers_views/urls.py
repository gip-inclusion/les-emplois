from django.urls import path, re_path

from itou.www.prescribers_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "prescribers_views"

urlpatterns = [
    path("edit_organization", views.edit_organization, name="edit_organization"),
    path("colleagues", views.members, name="members"),
    path("<int:org_id>/card", views.card, name="card"),
    path("deactivate_member/<int:user_id>", views.deactivate_member, name="deactivate_member"),
    # Can't mix capture var syntaxes in `re_path`: all path vars expressed as RE
    re_path(
        "admin_role/(?P<action>add|remove)/(?P<user_id>[0-9]+)", views.update_admin_role, name="update_admin_role"
    ),
]
