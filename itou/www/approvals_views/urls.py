from django.urls import path

from itou.www.approvals_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "approvals"

urlpatterns = [
    # PASS IAE
    path("detail/<int:pk>", views.ApprovalDetailView.as_view(), name="detail"),
    path("display/<int:approval_id>", views.ApprovalPrintableDisplay.as_view(), name="display_printable_approval"),
    path("list", views.ApprovalListView.as_view(), name="list"),
    path("declare_prolongation/<int:approval_id>", views.declare_prolongation, name="declare_prolongation"),
    path(
        "declare_prolongation/<int:approval_id>/check_prescriber_email",
        views.CheckPrescriberEmailView.as_view(),
        name="check_prescriber_email",
    ),
    path(
        "declare_prolongation/<int:approval_id>/check_contact_details",
        views.CheckContactDetailsView.as_view(),
        name="check_contact_details",
    ),
    path(
        "declare_prolongation/<int:approval_id>/prolongation_form_for_reason",
        views.UpdateFormForReasonView.as_view(),
        name="prolongation_form_for_reason",
    ),
    path("prolongation/requests", views.prolongation_requests_list, name="prolongation_requests_list"),
    path(
        "prolongation/request/<int:prolongation_request_id>",
        views.ProlongationRequestShowView.as_view(),
        name="prolongation_request_show",
    ),
    path(
        "prolongation/request/<int:prolongation_request_id>/report-file/",
        views.prolongation_request_report_file,
        name="prolongation_request_report_file",
    ),
    path(
        "prolongation/request/<int:prolongation_request_id>/grant",
        views.ProlongationRequestGrantView.as_view(),
        name="prolongation_request_grant",
    ),
    path(
        "prolongation/request/<int:prolongation_request_id>/deny",
        views.ProlongationRequestDenyView.as_view(url_name="approvals:prolongation_request_deny"),
        name="prolongation_request_deny",
    ),
    path(
        "prolongation/request/<int:prolongation_request_id>/deny/<slug:step>",
        views.ProlongationRequestDenyView.as_view(url_name="approvals:prolongation_request_deny"),
        name="prolongation_request_deny",
    ),
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
