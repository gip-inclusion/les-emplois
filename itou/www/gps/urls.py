from django.urls import path

from itou.www.gps import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "gps"

urlpatterns = [
    path("groups", views.my_groups, name="my_groups"),
    path("groups/join", views.join_group, name="join_group"),
    path("groups/<int:group_id>/leave", views.leave_group, name="leave_group"),
    path("groups/<int:group_id>/toggle_referent", views.toggle_referent, name="toggle_referent"),
]
