from django.urls import path

from . import views

app_name = "services"

urlpatterns = [
    path("<str:uid>", views.ServiceDetailView.as_view(), name="detail"),
]