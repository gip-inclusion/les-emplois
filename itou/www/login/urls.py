from django.urls import path

from itou.www.login import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "login"

urlpatterns = [
    path("existing/<uuid:user_public_id>", views.ExistingUserLoginView.as_view(), name="existing_user"),
    path("verify", views.VerifyOTPView.as_view(), name="verify_otp"),
    path("demo", views.demo_login_view, name="demo"),
    # Retro compatibility url
    path("job_seeker", views.PreLoginView.as_view(), name="job_seeker"),  # FIXME use redirect instead ?
]
