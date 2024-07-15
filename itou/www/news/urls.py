from django.urls import path

from itou.www.news import views


app_name = "news"


urlpatterns = [
    path("", views.NewsView.as_view(), name="home"),
]
