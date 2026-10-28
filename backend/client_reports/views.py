from rest_framework import generics

from .models import Client
from .serializers import ClientSerializer


class ClientListCreateView(generics.ListCreateAPIView):
    serializer_class = ClientSerializer

    def get_queryset(self):
        return Client.objects.filter(advisor=self.request.user)

    def perform_create(self, serializer):
        serializer.save(advisor=self.request.user)
