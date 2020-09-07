from rest_framework import viewsets

from apps.events.models import Event
from .serilaizers import EventScheduleSerializer


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by("-created")
    serializer_class = EventScheduleSerializer

    def get_queryset(self):
        if self.request.GET.get('event_status'):
            return Event.objects.filter(status=self.request.GET.get('event_status')).order_by('-created')
        else:
            return Event.objects.all()
