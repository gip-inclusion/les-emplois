from django.urls import path
from django.views.generic import TemplateView


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "content"

urlpatterns = [
    path("faq/", TemplateView.as_view(template_name="content/faq.html"), name="faq"),
]
