from django.urls import path

from itou.www.prescribers_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "prescribers_views"

urlpatterns = [
    path("edit_organization", views.edit_organization, name="edit_organization"),
    path("colleagues", views.member_list, name="members"),
    path("<int:org_id>/card", views.card, name="card"),
    path("deactivate_member/<uuid:public_id>", views.deactivate_member, name="deactivate_member"),
    path("admin_role/<str:action>/<uuid:public_id>", views.update_admin_role, name="update_admin_role"),
    path("list_accredited_organizations", views.list_accredited_organizations, name="list_accredited_organizations"),
]
