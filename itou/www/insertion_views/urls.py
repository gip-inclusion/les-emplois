from django.urls import path

from itou.www.insertion_views import views


app_name = "insertion_views"

urlpatterns = [
    path("structure/<str:structure_uid>/card", views.StructureCardView.as_view(), name="structure_card"),
]
