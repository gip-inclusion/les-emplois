from django.urls import path

from itou.www.professionals_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "professionals_views"

urlpatterns = [
    path("authorizations/list", views.AuthorizationListView.as_view(), name="authorizations_list"),
    path("authorizations/details/<uuid:uid>", views.AuthorizationDetailsView.as_view(), name="authorizations_details"),
]
