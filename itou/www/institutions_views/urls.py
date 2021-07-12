from django.urls import path, re_path

from itou.www.institutions_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "institutions_views"

urlpatterns = [
    path("colleagues", views.member_list, name="members"),
    path("deactivate_member/<int:user_id>", views.deactivate_member, name="deactivate_member"),
    # # Can't mix capture var syntaxes in `re_path`: all path vars expressed as RE
    re_path(
        "admin_role/(?P<action>add|remove)/(?P<user_id>[0-9]+)", views.update_admin_role, name="update_admin_role"
    ),
]
