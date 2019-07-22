from django.urls import path

from itou.siae import views

urlpatterns = [

    path('', views.details, name='details'),

]
