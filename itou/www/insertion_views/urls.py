from django.urls import path

from itou.www.insertion_views import views


app_name = "insertion_views"

urlpatterns = [
    path("structures/<str:structure_uid>/", views.StructureCardView.as_view(), name="structure_card"),
    path("services/<str:service_uid>/", views.ServiceDetailView.as_view(), name="service_detail"),
]
