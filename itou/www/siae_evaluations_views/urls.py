from django.urls import path

from itou.www.siae_evaluations_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siae_evaluations_views"

urlpatterns = [
    path("samples_selection", views.samples_selection, name="samples_selection"),
]
