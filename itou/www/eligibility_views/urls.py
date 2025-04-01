from django.urls import path

from itou.www.eligibility_views import views


app_name = "eligibility_views"

urlpatterns = [
    path(
        "<uuid:job_seeker_public_id>/update",
        views.UpdateEligibilityView.as_view(),
        name="update",
        kwargs={"standalone_process": True},
    ),
    path(
        "update/<uuid:job_seeker_public_id>/<int:company_pk>",
        views.UpdateEligibilityView.as_view(),
        name="update",
        kwargs={"prescription_process": True},
    ),
]
