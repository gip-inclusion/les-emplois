from django.urls import path

from . import views


app_name = "pe_connect"

urlpatterns = [
    path("authorize", views.pe_connect_authorize, name="authorize"),
    path("callback", views.pe_connect_callback, name="callback"),
    path("logout", views.pe_connect_logout, name="logout"),
]
