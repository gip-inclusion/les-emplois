from django.urls import path

from itou.www.autocomplete import views

# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "autocomplete"

urlpatterns = [
    path("cities", views.cities_autocomplete, name="cities"),
    path("jobs", views.jobs_autocomplete, name="jobs"),
]
