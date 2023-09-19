from django.urls import path

from itou.www.security import views


urlpatterns = [
    path(".well-known/security.txt", views.security_txt, name="security-txt"),
]
