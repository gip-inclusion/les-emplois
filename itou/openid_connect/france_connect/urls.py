from django.urls import path

from . import views


app_name = "france_connect"

urlpatterns = [
    path("authorize", views.france_connect_authorize, name="authorize"),
    path("callback", views.france_connect_callback, name="callback"),
    path("logout", views.france_connect_logout, name="logout"),
]
