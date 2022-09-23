from django.urls import path

from itou.www.approvals_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "approvals"

urlpatterns = [
    # PASS IAE
    path("detail/<int:pk>", views.ApprovalDetailView.as_view(), name="detail"),
    path("display/<int:approval_id>", views.display_printable_approval, name="display_printable_approval"),
    path("list", views.ApprovalListView.as_view(), name="list"),
    path("declare_prolongation/<int:approval_id>", views.declare_prolongation, name="declare_prolongation"),
    path("suspend/<int:approval_id>", views.suspend, name="suspend"),
    path("suspension/<int:suspension_id>/edit", views.suspension_update, name="suspension_update"),
    path("suspension/<int:suspension_id>/delete", views.suspension_delete, name="suspension_delete"),
    # PE Approvals
    path("pe-approval/search", views.pe_approval_search, name="pe_approval_search"),
    path(
        "pe-approval/<int:pe_approval_id>/search-user", views.pe_approval_search_user, name="pe_approval_search_user"
    ),
    path(
        "pe-approval/<int:pe_approval_id>/create",
        views.pe_approval_create,
        name="pe_approval_create",
    ),
]
