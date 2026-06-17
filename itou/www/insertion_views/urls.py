from django.urls import path

from itou.www.insertion_views import views


app_name = "insertion_views"

urlpatterns = [
    path("structures/<str:structure_uid>/", views.StructureCardView.as_view(), name="structure_card"),
    path("services/<str:service_uid>/", views.ServiceDetailView.as_view(), name="service_detail"),
    path(
        "orientations/<str:service_uid>/start/",
        views.start_orientation,
        name="start_orientation",
    ),
    path(
        "orientations/<str:service_uid>/job-seeker/",
        views.OrientationSelectJobSeekerView.as_view(),
        name="orientation_select_job_seeker",
    ),
    path(
        "orientations/<uuid:session_uuid>/create/<slug:step>/",
        views.OrientationWizardView.as_view(),
        name="orientation_steps",
    ),
    path(
        "orientations/<uuid:session_uuid>/dismiss-disclaimer/",
        views.dismiss_orientation_disclaimer,
        name="orientation_dismiss_disclaimer",
    ),
    path(
        "orientations/<str:service_uid>/confirmation/",
        views.OrientationConfirmationView.as_view(),
        name="orientation_confirmation",
    ),
]
