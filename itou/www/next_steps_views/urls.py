from django.urls import path

from itou.www.next_steps_views import views


app_name = "next_steps_views"

urlpatterns = [
    path("", views.todo, name="todo"),
    path("job-seekers/<uuid:public_id>", views.job_seeker, name="job_seeker"),
    path("job-seekers/<uuid:public_id>/advisors/<int:assignment_pk>", views.advisor, name="advisor"),
    path("job-seekers/<uuid:public_id>/orientations/<uuid:orientation_id>", views.orientation, name="orientation"),
    path(
        "job-seekers/<uuid:public_id>/job-applications/<uuid:job_application_id>",
        views.job_application,
        name="job_application",
    ),
    path("job-seekers/<uuid:public_id>/suspensions/<int:suspension_id>", views.suspension, name="suspension"),
    path("job-seekers/<uuid:public_id>/eligibility", views.eligibility, name="eligibility"),
    path(
        "job-seekers/<uuid:public_id>/pro-support-reports/<uuid:report_id>",
        views.pro_support_report,
        name="pro_support_report",
    ),
    path("journeys/<slug:kind>/<str:pk>", views.journey, name="journey"),
]
