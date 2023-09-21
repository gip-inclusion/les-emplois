from django.urls import path

from itou.www.search import views


app_name = "search"

urlpatterns = [
    path("employers", views.employer_search_home, name="siaes_home"),
    path("employers/results", views.EmployerSearchView.as_view(), name="siaes_results"),
    path("job-descriptions/results", views.JobDescriptionSearchView.as_view(), name="job_descriptions_results"),
    path("prescribers", views.search_prescribers_home, name="prescribers_home"),
    path("prescribers/results", views.search_prescribers_results, name="prescribers_results"),
]
