from django.urls import path

from itou.www.gps import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "gps"

urlpatterns = [
    path("my_groups", views.my_groups, name="my_groups"),
    path("join_group", views.join_group, name="join_group"),
]
