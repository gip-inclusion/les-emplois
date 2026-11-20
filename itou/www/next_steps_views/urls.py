from django.urls import path

from itou.www.next_steps_views import views


app_name = "next_steps_views"

urlpatterns = [
    path("", views.todo, name="todo"),
    path("job-seekers/<uuid:public_id>", views.job_seeker, name="job_seeker"),
    path("job-seekers/<uuid:public_id>/advisors/<int:assignment_pk>", views.advisor, name="advisor"),
    path(
        "job-seekers/<uuid:public_id>/advisors/<int:assignment_pk>/end",
        views.end_assignment,
        name="end_assignment",
    ),
    path("job-seekers/<uuid:public_id>/orientations/<uuid:orientation_id>", views.orientation, name="orientation"),
    path(
        "job-seekers/<uuid:public_id>/job-applications/<uuid:job_application_id>",
        views.job_application,
        name="job_application",
    ),
    path("job-seekers/<uuid:public_id>/suspensions/<int:suspension_id>", views.suspension, name="suspension"),
    path("job-seekers/<uuid:public_id>/eligibility", views.eligibility, name="eligibility"),
    path("job-seekers/<uuid:public_id>/approval", views.approval, name="approval"),
    path(
        "job-seekers/<uuid:public_id>/barriers/<slug:barrier>/solutions",
        views.solutions,
        name="solutions",
    ),
    path("job-seekers/<uuid:public_id>/services/<int:service_id>", views.service, name="service"),
    path(
        "job-seekers/<uuid:public_id>/barriers/<slug:barrier>/<slug:action>",
        views.barrier_statement,
        name="barrier_statement",
    ),
    path("job-seekers/<uuid:public_id>/contracts/<int:contract_id>", views.contract, name="contract"),
    path(
        "job-seekers/<uuid:public_id>/pro-support-reports/<uuid:report_id>",
        views.pro_support_report,
        name="pro_support_report",
    ),
    path("journeys/<slug:kind>/<str:pk>", views.journey, name="journey"),
]
