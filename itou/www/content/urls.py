from django.urls import path
from django.views.generic import TemplateView


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "content"

urlpatterns = [
    path("faq/", TemplateView.as_view(template_name="content/faq.html"), name="faq"),
    path(
        "qui_sommes_nous/",
        TemplateView.as_view(template_name="content/qui_sommes_nous.html"),
        name="qui_sommes_nous",
    ),
]
