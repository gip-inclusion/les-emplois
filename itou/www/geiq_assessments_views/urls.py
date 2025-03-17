from django.urls import path

from itou.www.geiq_assessments_views import views


app_name = "geiq_assessments_views"

urlpatterns = [
    path("list", views.list_for_geiq, name="list_for_geiq"),
    path("create", views.create_assessment, name="create"),
]
