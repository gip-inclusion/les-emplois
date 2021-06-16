from django.urls import path

from itou.www.approvals_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "approvals"

urlpatterns = [
    path("download/<uuid:job_application_id>", views.approval_as_pdf, name="approval_as_pdf"),
    path("declare_prolongation/<int:approval_id>", views.declare_prolongation, name="declare_prolongation"),
    path("suspend/<int:approval_id>", views.suspend, name="suspend"),
    path("suspension/<int:suspension_id>/edit", views.suspension_update, name="suspension_update"),
    path("suspension/<int:suspension_id>/delete", views.suspension_delete, name="suspension_delete"),
    path("search-pe-approval/", views.search_pe_approval, name="search_pe_approval"),
    path("search-user/<int:pe_approval_id>", views.search_user, name="search_user"),
    path(
        "complete-pe-approval/<int:pe_approval_id>",
        views.create_approval_from_pe_approval,
        name="create_approval_from_pe_approval",
    ),
]
