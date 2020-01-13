from django.urls import path

from itou.www.signup import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "signup"

urlpatterns = [
    path("prescriber", views.PrescriberSignupView.as_view(), name="prescriber"),
    path("siae", views.SiaeSignupView.as_view(), name="siae"),
    path("job_seeker", views.JobSeekerSignupView.as_view(), name="job_seeker"),
    path(
        "validation/<uuid:user_uuid>/<str:secret>", views.validation, name="validation"
    ),
    path(
        "account_inactive/<uuid:user_uuid>",
        views.account_inactive,
        name="account_inactive",
    ),
    path(
        "delete_account_pending_validation/<uuid:user_uuid>",
        views.delete_account_pending_validation,
        name="delete_account_pending_validation",
    ),
]
