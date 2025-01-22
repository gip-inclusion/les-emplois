from django.urls import path

from itou.openid_connect.france_connect import views


app_name = "france_connect"

urlpatterns = [
    path("authorize", views.france_connect_authorize, name="authorize"),
    path("callback", views.france_connect_callback, name="callback"),
    path("logout", views.france_connect_logout, name="logout"),
]
