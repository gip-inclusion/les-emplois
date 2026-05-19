from django.urls import path

from itou.www.insertion_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "insertion_views"

urlpatterns = [
    path("structure/<str:structure_uid>/card", views.StructureCardView.as_view(), name="structure_card"),
    path("service/<str:service_uid>/card", views.ServiceCardView.as_view(), name="service_card"),
    path("orienter/<str:service_uid>/start/", views.start_orientation, name="start_orientation"),
    path("orienter/<uuid:session_uuid>/<str:step>/", views.OrientationWizardView.as_view(), name="orientation_steps"),
    path("safe-upload/", views.safe_upload_proxy, name="safe_upload"),
]
