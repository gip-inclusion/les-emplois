from django.urls import path

from itou.www.apply import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "apply"

urlpatterns = [
    path("<siret:siret>", views.submit_for_job_seeker, name="submit_for_job_seeker"),
    path("list", views.list_for_job_seeker, name="list_for_job_seeker"),
    path(
        "siae/detail/<uuid:job_application_id>",
        views.detail_for_siae,
        name="detail_for_siae",
    ),
    path("siae/list", views.list_for_siae, name="list_for_siae"),
]
