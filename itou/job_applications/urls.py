from django.urls import re_path

from itou.job_applications import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "job_applications"

urlpatterns = [
    re_path(r"^(?P<siret>\d{14})/job_request$", views.send_job_request, name="job_request")
]
