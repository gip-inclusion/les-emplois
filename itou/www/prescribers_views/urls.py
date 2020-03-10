from django.urls import path

from itou.www.prescribers_views import views

# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "prescribers_views"

urlpatterns = [
    path("create_organization", views.create_organization, name="create_organization"),
    path("edit_organization", views.edit_organization, name="edit_organization"),
]
