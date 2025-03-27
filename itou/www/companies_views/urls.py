from django.urls import path

from itou.www.companies_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "companies_views"

urlpatterns = [
    path("overview", views.overview, name="overview"),
    path("<int:siae_id>/card", views.CompanyCardView.as_view(), name="card"),
    path(
        "job_description/<int:job_description_id>/card",
        views.JobDescriptionCardView.as_view(),
        name="job_description_card",
    ),
    path("job_description_list", views.job_description_list, name="job_description_list"),
    path("edit_job_description", views.edit_job_description, name="edit_job_description"),
    path("edit_job_description/<uuid:edit_session_id>", views.edit_job_description, name="edit_job_description"),
    path("edit_job_description/<int:job_description_id>", views.edit_job_description, name="edit_job_description"),
    path(
        "edit_job_description/<int:job_description_id>/<uuid:edit_session_id>",
        views.edit_job_description,
        name="edit_job_description",
    ),
    # TODO (François): Remove URL without parameter after a week.
    path("edit_job_description_details", views.edit_job_description_details, name="edit_job_description_details"),
    path(
        "edit_job_description_details/<uuid:edit_session_id>",
        views.edit_job_description_details,
        name="edit_job_description_details",
    ),
    path(
        "edit_job_description_details/<int:job_description_id>/<uuid:edit_session_id>",
        views.edit_job_description_details,
        name="edit_job_description_details",
    ),
    # TODO (François): Remove URL without parameter after a week.
    path("edit_job_description_preview", views.edit_job_description_preview, name="edit_job_description_preview"),
    path(
        "edit_job_description_preview/<uuid:edit_session_id>",
        views.edit_job_description_preview,
        name="edit_job_description_preview",
    ),
    path(
        "edit_job_description_preview/<int:job_description_id>/<uuid:edit_session_id>",
        views.edit_job_description_preview,
        name="edit_job_description_preview",
    ),
    # TODO(François): Remove URL after a week.
    path(
        "update_job_description/<int:job_description_id>", views.update_job_description, name="update_job_description"
    ),
    path("show_financial_annexes", views.show_financial_annexes, name="show_financial_annexes"),
    path("select_financial_annex", views.select_financial_annex, name="select_financial_annex"),
    path("create-company", views.create_company, name="create_company"),
    path("edit-company", views.edit_company_step_contact_infos, name="edit_company_step_contact_infos"),
    path("edit-company-description", views.edit_company_step_description, name="edit_company_step_description"),
    path("edit-company-preview", views.edit_company_step_preview, name="edit_company_step_preview"),
    path("colleagues", views.members, name="members"),
    path("deactivate_member/<uuid:public_id>", views.deactivate_member, name="deactivate_member"),
    path("admin_role/<str:action>/<uuid:public_id>", views.update_admin_role, name="update_admin_role"),
    path("dora-services/<str:code_insee>", views.hx_dora_services, name="hx_dora_services"),
    path(
        "dora-service-redirect/<str:source>/<str:service_id>",
        views.dora_service_redirect,
        name="dora_service_redirect",
    ),
]
