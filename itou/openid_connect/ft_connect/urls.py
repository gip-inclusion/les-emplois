from django.urls import path

from itou.openid_connect.ft_connect import views


app_name = "ft_connect"

urlpatterns = [
    path("authorize", views.ft_connect_authorize, name="authorize"),
    path("callback", views.ft_connect_callback, name="callback"),
    path("error", views.ft_connect_no_email, name="no_email"),
    path("logout", views.ft_connect_logout, name="logout"),
]
