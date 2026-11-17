from django.urls import path

from itou.www.next_steps_views import views


app_name = "next_steps_views"

urlpatterns = [
    path("", views.todo, name="todo"),
    path("job-seekers/<uuid:public_id>", views.job_seeker, name="job_seeker"),
    path("job-seekers/<uuid:public_id>/advisors/<int:assignment_pk>", views.advisor, name="advisor"),
    path("journeys/<slug:kind>/<str:pk>", views.journey, name="journey"),
]
