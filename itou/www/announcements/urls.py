from django.urls import path

from itou.www.announcements import views


app_name = "announcements"


urlpatterns = [
    path("news/", views.NewsView.as_view(), name="news"),
]
