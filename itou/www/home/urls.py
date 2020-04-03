from django.urls import path

from itou.www.home import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "home"


urlpatterns = [
    path("", views.home, name="hp"),
    path("achat", views.home_achat, name="hp_achat"),
    path("sentry-debug/", views.trigger_error, name="sentry_debug"),
]
