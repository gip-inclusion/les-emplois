from django.urls import path, re_path

from itou.www.institutions_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "institutions_views"

urlpatterns = [
    path("colleagues", views.member_list, name="members"),
    path("deactivate_member/<uuid:public_id>", views.deactivate_member, name="deactivate_member"),
    # to be removed when old url is not used anymore
    path("deactivate_member/<int:user_id>", views.deactivate_member_temp_redirection, name="deactivate_member"),
    # # Can't mix capture var syntaxes in `re_path`: all path vars expressed as RE
    re_path(
        "admin_role/(?P<action>add|remove)/(?P<public_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        views.update_admin_role,
        name="update_admin_role",
    ),
]
