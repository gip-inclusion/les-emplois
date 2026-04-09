from django.urls import path

from itou.www.services import views


app_name = "services"

urlpatterns = [
    path("<str:uid>", views.ServiceDetailView.as_view(), name="detail"),
]
