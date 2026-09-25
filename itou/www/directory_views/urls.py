from django.urls import path

from itou.www.directory_views import views


app_name = "directory"

urlpatterns = [
    path("", views.people_results, name="people_results"),
    path("personnes/<str:key>/", views.person_detail, name="person_detail"),
    path("personnes/<str:key>/contact/<str:field>/", views.reveal_contact, name="reveal_contact"),
    path("personnes/<str:key>/message/", views.send_message, name="send_message"),
]
