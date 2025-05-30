from django.urls import path

from itou.www.eligibility_views import views


app_name = "eligibility_views"

urlpatterns = [
    # FIXME(alaurent) remove in a week
    path("update/<uuid:job_seeker_public_id>", views.UpdateIAEEligibilityView.as_view()),
    path("update/iae/<uuid:job_seeker_public_id>", views.UpdateIAEEligibilityView.as_view(), name="update_iae"),
]
