from django.urls import path

from itou.www.siaes_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siaes_views"

urlpatterns = [
    path("<siret:siret>/card", views.card, name="card"),
    path("configure_jobs", views.configure_jobs, name="configure_jobs"),
    path("edit_siae", views.edit_siae, name="edit_siae"),
]
