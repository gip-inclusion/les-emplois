from django.urls import re_path

from itou.www.apply import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "apply"

urlpatterns = [re_path(r"^(?P<siret>\d{14})$", views.apply, name="form")]
