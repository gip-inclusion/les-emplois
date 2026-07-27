from django.urls import path

from itou.www.login import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "login"

urlpatterns = [
    path("existing", views.ExistingUserLoginView.as_view(), name="existing_user"),
    path("demo", views.demo_login_view, name="demo"),
    # Retro compatibility url
    # FIXME(alaurent) This url was used in new_for_job_seeker_body until 21/05. Remove in december 2026
    path("job_seeker", views.PreLoginView.as_view(), name="job_seeker"),
]
