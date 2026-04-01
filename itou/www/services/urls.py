from django.urls import path

from . import views

urlpatterns = [
    path("<str:uid>", views.ServiceDetailView.as_view(), name="detail"),
]