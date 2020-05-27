from django.urls import path

from itou.www.signup import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "signup"

urlpatterns = [
    path("select_prescriber_type", views.select_prescriber_type, name="select_prescriber_type"),
    path("prescriber/orienter", views.OrienterPrescriberView.as_view(), name="prescriber_orienter"),
    path("prescriber/poleemploi", views.PoleEmploiPrescriberView.as_view(), name="prescriber_poleemploi"),
    path("prescriber/authorized", views.AuthorizedPrescriberView.as_view(), name="prescriber_authorized"),
    path("select_siae", views.select_siae, name="select_siae"),
    path("siae/<str:encoded_siae_id>/<str:token>", views.SiaeSignupView.as_view(), name="siae"),
    path("siae", views.SiaeSignupView.as_view(), name="siae"),
    path("job_seeker", views.JobSeekerSignupView.as_view(), name="job_seeker"),
    path("from_invitation/<str:encoded_invitation_id>", views.FromInvitationView.as_view(), name="from_invitation"),
]
