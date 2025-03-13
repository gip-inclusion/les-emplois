from django.urls import path

from itou.www.institutions_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "institutions_views"

urlpatterns = [
    path("colleagues", views.member_list, name="members"),
    path("deactivate_member/<uuid:public_id>", views.deactivate_member, name="deactivate_member"),
    path("admin_role/<str:action>/<uuid:public_id>", views.update_admin_role, name="update_admin_role"),
]
