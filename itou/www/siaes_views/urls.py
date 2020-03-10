from django.urls import path

from itou.www.siaes_views import views

# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siaes_views"

urlpatterns = [
    # First match for legacy siret route then only for current pk route.
    # Otherwise siret would be interpreted as id first and fail.
    path("<siret:siret>/card", views.card_legacy, name="card_legacy"),
    path("<int:siae_id>/card", views.card, name="card"),
    path(
        "job_description/<int:job_description_id>/card",
        views.job_description_card,
        name="job_description_card",
    ),
    path("configure_jobs", views.configure_jobs, name="configure_jobs"),
    path("create_siae", views.create_siae, name="create_siae"),
    path("edit_siae", views.edit_siae, name="edit_siae"),
]
