from django.urls import path, re_path

from itou.www.apply import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "apply"

urlpatterns = [
    re_path(
        r"^(?P<siret>\d{14})$",
        views.submit_for_job_seeker,
        name="submit_for_job_seeker",
    ),
    path("list", views.list_for_siae, name="list_for_siae"),
    path(
        "detail/<uuid:job_application_id>",
        views.detail_for_siae,
        name="detail_for_siae",
    ),
]
