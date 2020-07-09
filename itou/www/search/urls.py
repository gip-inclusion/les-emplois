from django.urls import path

from itou.www.search import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "search"

urlpatterns = [
    path("employers", views.search_siaes_home, name="siaes_home"),
    path("employers/results", views.search_siaes_results, name="siaes_results"),
    path("prescribers", views.search_prescribers_home, name="prescribers_home"),
    path("prescribers/results", views.search_prescribers_results, name="prescribers_results"),
]
