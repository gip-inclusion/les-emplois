from django.urls import path

from itou.www.directory_views import views


app_name = "directory"

urlpatterns = [
    path("", views.people_results, name="people_results"),
    path("<str:membership_kind>/<int:membership_id>", views.membership_detail, name="membership_detail"),
]
