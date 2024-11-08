from django.urls import path

from itou.www.logout import views


app_name = "logout"

urlpatterns = [
    path("warning/<str:kind>", views.LogoutWarningView.as_view(), name="warning"),
]
