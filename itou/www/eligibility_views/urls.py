from django.urls import path

from itou.www.eligibility_views import views


app_name = "eligibility_views"

urlpatterns = [
    path(
        "update/<uuid:job_seeker_public_id>",
        views.UpdateEligibilityView.as_view(),
        name="update",
        kwargs={"tunnel": "standalone_process"},
    ),
]
