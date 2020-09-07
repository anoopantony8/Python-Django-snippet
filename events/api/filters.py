from django_filters import rest_framework as filters
from apps.events.models import (Shift, Event)


class ShiftFilter(filters.FilterSet):
    start_date_gte = filters.DateFilter(
        field_name="start_date", lookup_expr='gte')
    start_date_lte = filters.DateFilter(
        field_name="start_date", lookup_expr='lte')
    start_date_time_gte = filters.DateTimeFilter(
        field_name="start_date", lookup_expr='gte')
    start_date_time_lte = filters.DateTimeFilter(
        field_name="start_date", lookup_expr='lte')
    status = filters.MultipleChoiceFilter(choices=Shift.STATUS, )

    class Meta:
        model = Shift
        fields = ['id', 'name', 'event', 'location', 'start_date', 'end_date',
                  'start_date_gte', 'start_date_lte', 'status', 'start_date_time_gte', 'start_date_time_lte']


class EventFilter(filters.FilterSet):
    start_date_gte = filters.DateFilter(
        field_name="start_date", lookup_expr='gte')
    start_date_lte = filters.DateFilter(
        field_name="start_date", lookup_expr='lte')
    status = filters.MultipleChoiceFilter(choices=Event.STATUS, )

    class Meta:
        model = Event
        fields = ['id', 'event_type', 'status',
        'client', 'start_date', 'end_date', 'location']
