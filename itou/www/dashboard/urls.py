from django.urls import path

from itou.www.dashboard import views

# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("edit_user_info", views.edit_user_info, name="edit_user_info"),
    path("switch_siae", views.switch_siae, name="switch_siae"),
]
