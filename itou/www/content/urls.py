from django.urls import path
from django.views.generic import TemplateView


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "content"

urlpatterns = [
    path("faq/", TemplateView.as_view(template_name="content/faq.html"), name="faq"),
    path(
        "experimentation/",
        TemplateView.as_view(template_name="content/experimentation.html"),
        name="experimentation",
    ),
    path(
        "inclusion_kesako/",
        TemplateView.as_view(template_name="content/inclusion_kesako.html"),
        name="inclusion_kesako",
    ),
    path(
        "qui_sommes_nous/",
        TemplateView.as_view(template_name="content/qui_sommes_nous.html"),
        name="qui_sommes_nous",
    ),
]
