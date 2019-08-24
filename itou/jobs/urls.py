from django.urls import path

from itou.jobs import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "jobs"

urlpatterns = [path("autocomplete", views.autocomplete, name="autocomplete")]
