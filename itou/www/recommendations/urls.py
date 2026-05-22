from django.urls import path

from itou.www.recommendations import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "recommendations"

urlpatterns = [
    path("beneficiary/list", views.list_users, name="beneficiary_list"),
]
