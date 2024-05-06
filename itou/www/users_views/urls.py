from django.urls import path

from itou.www.users_views import views


app_name = "users"

urlpatterns = [
    path("details/<uuid:public_id>", views.UserDetailsView.as_view(), name="details"),
]
