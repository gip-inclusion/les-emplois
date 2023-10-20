from django.urls import path

from . import views


app_name = "inclusion_connect"

urlpatterns = [
    path("authorize", views.inclusion_connect_authorize, name="authorize"),
    path("activate_account", views.inclusion_connect_activate_account, name="activate_account"),
    path("callback", views.inclusion_connect_callback, name="callback"),
    path("logout", views.inclusion_connect_logout, name="logout"),
]
