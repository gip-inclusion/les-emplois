from django.urls import path

from itou.www.next_steps_views import views


app_name = "next_steps_views"

urlpatterns = [
    path("", views.todo, name="todo"),
    path("journeys/<slug:kind>/<str:pk>", views.journey, name="journey"),
]
