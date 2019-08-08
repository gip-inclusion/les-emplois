from django.urls import path

from itou.cities import views


# https://docs.djangoproject.com/en/dev/topics/http/urls/#url-namespaces-and-included-urlconfs
app_name = 'city'

urlpatterns = [

    path('autocomplete', views.autocomplete, name='autocomplete'),

]
