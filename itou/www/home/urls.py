from django.urls import path

from itou.www.home import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "home"


urlpatterns = [
    path("", views.home, name="hp"),
    path("sentry-debug/", views.trigger_error, name="sentry_debug"),
    path("duet-date-picker/", views.duet_date_picker, name="duet_date_picker"),
]
