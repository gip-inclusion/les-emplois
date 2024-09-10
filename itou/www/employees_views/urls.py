from django.urls import path

from itou.www.employees_views import views


app_name = "employees"

urlpatterns = [
    path("detail/<uuid:public_id>", views.EmployeeDetailView.as_view(), name="detail"),
]
