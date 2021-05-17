from django.urls import path

from itou.www.employee_record_views import views


app_name = "employee_record_views"

urlpatterns = [
    path("list", views.list, name="list"),
    # Next: path of employee records actions
]
