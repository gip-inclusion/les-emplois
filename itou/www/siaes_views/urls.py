from django.urls import re_path

from itou.www.siaes_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siaes_views"

urlpatterns = [re_path(r"^(?P<siret>\d{14})/card$", views.card, name="card")]
