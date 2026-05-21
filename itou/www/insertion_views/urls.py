from django.urls import path

from itou.www.insertion_views import views


app_name = "insertion_views"

urlpatterns = [
    path("structure/<str:structure_uid>/card", views.StructureCardView.as_view(), name="structure_card"),
    path("service/<str:service_uid>/card", views.ServiceCardView.as_view(), name="service_card"),
    path("orienter/<str:service_uid>/start/", views.start_orientation, name="start_orientation"),
    path(
        "orienter/<uuid:session_uuid>/<slug:step>/",
        views.OrientationWizardView.as_view(),
        name="orientation_steps",
    ),
    path(
        "orienter/<str:service_uid>/confirmation/",
        views.OrientationConfirmationView.as_view(),
        name="orientation_confirmation",
    ),
    path(
        "orienter/<str:service_uid>/erreur/",
        views.OrientationErrorView.as_view(),
        name="orientation_error",
    ),
]
