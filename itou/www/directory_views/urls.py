from django.urls import path

from itou.www.directory_views import views


app_name = "directory"

urlpatterns = [
    path("", views.people_results, name="people_results"),
    path("person/<uuid:public_id>/", views.person_detail, name="person_detail"),
    path("person/<uuid:public_id>/message/", views.send_message, name="send_message"),
]
