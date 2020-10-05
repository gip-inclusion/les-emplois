from django.urls import path

from itou.www.welcoming_tour import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "welcoming_tour"

urlpatterns = [
    path("index", views.index, name="index"),
]
