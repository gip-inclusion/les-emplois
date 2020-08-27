from django.urls import path

from itou.www.prescribers_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "prescribers_views"

urlpatterns = [
    path("edit_organization", views.edit_organization, name="edit_organization"),
    path("colleagues", views.members, name="members"),
    path("<int:org_id>/card", views.card, name="card"),
]
