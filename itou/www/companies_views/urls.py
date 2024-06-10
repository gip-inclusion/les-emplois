from django.urls import path, re_path

from itou.www.companies_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "companies_views"

urlpatterns = [
    path("<int:siae_id>/card", views.card, name="card"),
    path("job_description/<int:job_description_id>/card", views.job_description_card, name="job_description_card"),
    path("job_description_list", views.job_description_list, name="job_description_list"),
    path("edit_job_description", views.edit_job_description, name="edit_job_description"),
    path("edit_job_description_details", views.edit_job_description_details, name="edit_job_description_details"),
    path("edit_job_description_preview", views.edit_job_description_preview, name="edit_job_description_preview"),
    path(
        "update_job_description/<int:job_description_id>", views.update_job_description, name="update_job_description"
    ),
    path("show_financial_annexes", views.show_financial_annexes, name="show_financial_annexes"),
    path("select_financial_annex", views.select_financial_annex, name="select_financial_annex"),
    path("create-company", views.create_company, name="create_company"),
    path("edit-company", views.edit_company_step_contact_infos, name="edit_company_step_contact_infos"),
    path("edit-company-description", views.edit_company_step_description, name="edit_company_step_description"),
    path("edit-company-preview", views.edit_company_step_preview, name="edit_company_step_preview"),
    # FIXME temporary backward compatibility, remove after a few days
    path("create_siae", views.create_company, name="create_siae"),
    path("edit_siae", views.edit_company_step_contact_infos, name="edit_siae_step_contact_infos"),
    path("edit_siae_description", views.edit_company_step_description, name="edit_siae_step_description"),
    path("edit_siae_preview", views.edit_company_step_preview, name="edit_siae_step_preview"),
    path("colleagues", views.members, name="members"),
    path("deactivate_member/<int:user_id>", views.deactivate_member, name="deactivate_member"),
    # Tricky: when using `re_path` you CAN'T mix re parts with non re ones
    # here, user_id was defined as <int:user_id> and action as re
    # as a result the eval of the url fails silently (404)
    # ROT: if using `re_path`, use RE everywhere
    re_path(
        "admin_role/(?P<action>add|remove)/(?P<user_id>[0-9]+)", views.update_admin_role, name="update_admin_role"
    ),
    path("dora-services/<str:code_insee>", views.hx_dora_services, name="hx_dora_services"),
    path(
        "dora-service-redirect/<str:source>/<str:service_id>",
        views.dora_service_redirect,
        name="dora_service_redirect",
    ),
]
