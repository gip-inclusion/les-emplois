from django.urls import path

from itou.siae import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = 'siae'

urlpatterns = [

    path('card', views.card, name='card'),
    path('search', views.search, name='search'),

]
