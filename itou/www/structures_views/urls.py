from django.urls import path

from itou.www.structures_views import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = "structures_views"

urlpatterns = [
    path("<int:structure_pk>/card", views.StructureCardView.as_view(), name="card"),
]
