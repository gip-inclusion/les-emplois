from django.urls import path, re_path

from itou.www.siaes_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siaes_views"

urlpatterns = [
    path("<int:siae_id>/card", views.card, name="card"),
    path("job_description/<int:job_description_id>/card", views.job_description_card, name="job_description_card"),
    path("configure_jobs", views.configure_jobs, name="configure_jobs"),
    path("show_financial_annexes", views.show_financial_annexes, name="show_financial_annexes"),
    path("select_financial_annex", views.select_financial_annex, name="select_financial_annex"),
    path("create_siae", views.create_siae, name="create_siae"),
    path("edit_siae", views.edit_siae, name="edit_siae"),
    path("colleagues", views.members, name="members"),
    path("block_job_applications", views.block_job_applications, name="block_job_applications"),
    path("deactivate_member/<int:user_id>", views.deactivate_member, name="deactivate_member"),
    # Tricky: when using `re_path` you CAN'T mix re parts with non re ones
    # here, user_id was defined as <int:user_id> and action as re
    # as a result the eval of the url fails silently (404)
    # ROT: if using `re_path`, use RE everywhere
    re_path(
        "admin_role/(?P<action>add|remove)/(?P<user_id>[0-9]+)", views.update_admin_role, name="update_admin_role"
    ),
]
