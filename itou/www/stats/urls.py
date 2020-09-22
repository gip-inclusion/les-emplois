from django.urls import path

from itou.www.stats import views


app_name = "stats"

urlpatterns = [
    path("", views.public_stats, name="public_stats"),
    path("advanced/", views.advanced_stats, name="advanced_stats"),
    path("vip/", views.reporting, name="stats_vip"),
]
