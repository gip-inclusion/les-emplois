from django.urls import path

from itou.www.siaes_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "siaes_views"

urlpatterns = [
    path("<int:siae_id>/card", views.card, name="card"),
    path("job_description/<int:job_description_id>/card", views.job_description_card, name="job_description_card"),
    path("configure_jobs", views.configure_jobs, name="configure_jobs"),
    path("show_financial_annexes", views.show_financial_annexes, name="show_financial_annexes"),
    path("select_financial_annex", views.select_financial_annex, name="select_financial_annex"),
    path("create_siae", views.create_siae, name="create_siae"),
    path("edit_siae", views.edit_siae, name="edit_siae"),
    path("colleagues", views.members, name="members"),
    path("block_job_applications", views.block_job_applications, name="block_job_applications"),
]
