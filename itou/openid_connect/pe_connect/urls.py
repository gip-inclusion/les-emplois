from django.urls import path

from itou.openid_connect.pe_connect import views


app_name = "pe_connect"

urlpatterns = [
    path("authorize", views.pe_connect_authorize, name="authorize"),
    path("callback", views.pe_connect_callback, name="callback"),
    path("error", views.pe_connect_no_email, name="no_email"),
    path("logout", views.pe_connect_logout, name="logout"),
]
