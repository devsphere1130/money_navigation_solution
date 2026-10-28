from django.urls import path

from .views import ClientListCreateView

urlpatterns = [
    path('clients/', ClientListCreateView.as_view(), name='client-list'),
]
