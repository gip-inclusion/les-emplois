from django.contrib.auth.decorators import login_not_required
from django.urls import path
from django.views.generic import TemplateView


app_name = "api"


urlpatterns = [
    path("", login_not_required(TemplateView.as_view(template_name="api/index.html")), name="index"),
]
