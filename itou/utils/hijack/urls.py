from django.urls import path

from itou.utils.hijack import views


app_name = "hijack"
urlpatterns = [
    path("acquire/", views.AcquireUserView.as_view(), name="acquire"),
    path("release/", views.ReleaseUserView.as_view(), name="release"),
]
