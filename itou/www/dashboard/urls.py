from django.urls import path, re_path

from itou.www.dashboard import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="index"),
    re_path(
        r"^(?P<siret>\d{14})/configure_jobs$",
        views.configure_jobs,
        name="configure_jobs",
    ),
]
