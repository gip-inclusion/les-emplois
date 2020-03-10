from django.urls import path

from itou.www.stats import views

# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "stats"


urlpatterns = [path("", views.stats, name="index")]
