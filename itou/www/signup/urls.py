from django.urls import path

from itou.www.signup import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "signup"

urlpatterns = [
    path("prescriber", views.PrescriberSignupView.as_view(), name="prescriber"),
    path("select_siae", views.select_siae, name="select_siae"),
    path("siae/<str:encoded_siae_id>/<str:token>", views.SiaeSignupView.as_view(), name="siae"),
    path("siae", views.SiaeSignupView.as_view(), name="siae"),
    path("job_seeker", views.JobSeekerSignupView.as_view(), name="job_seeker"),
]
