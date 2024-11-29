from django.urls import path
from django.views.generic import TemplateView


app_name = "api"


urlpatterns = [
    path("", TemplateView.as_view(template_name="api/index.html"), name="index"),
]
