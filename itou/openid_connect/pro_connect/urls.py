from django.urls import path

from itou.openid_connect.pro_connect import views


app_name = "pro_connect"

urlpatterns = [
    path("authorize", views.pro_connect_authorize, name="authorize"),
    path("callback", views.pro_connect_callback, name="callback"),
    path("logout", views.pro_connect_logout, name="logout"),
    path("logout_callback", views.pro_connect_logout_callback, name="logout_callback"),
]
