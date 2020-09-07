from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import DateTimeField, ExpressionWrapper, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import ugettext as _
from django_filters.rest_framework import DjangoFilterBackend
from django.utils.timezone import make_aware, make_naive

from pinax.notifications.models import NoticeType, queue, send, send_now
from rest_framework import (exceptions, filters, generics, mixins, status,
                            views, viewsets)
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.serializers import CrewProfileLiteSerializer
from apps.accounts.models import CrewProfile, Skills, User
from apps.common.models import Equipments, Qualification
from apps.events.api.notifications import send_event_status_notification
from apps.events.models import (Event, EventType, Shift, ShiftEquipment,
                                ShiftQualification, QuickQuote)
from apps.timesheet.models import TimeSheet
from apps.events.api.utils import get_event_shift_status, update_event_status_from_shift
from apps.mixins import MethodSerializerMixin
from apps.scheduler.models import Schedule
from apps.suppliers.models import Suppliers
from apps.utils import add_hours

from .filters import ShiftFilter, EventFilter
from .serilaizers import (EventCreateSerializer, EventLiteSerializer,
                          EventScheduleSerializer, EventSerializer,
                          EventStatusSerializer, EventTypeSerializer,
                          ShiftCrewDetailSerializer, ShiftCrewDetailSerilizer,
                          ShiftCrewListingSerilizer, ShiftCrewSerilaizer,
                          ShiftEquipmentSerializer, ShiftLiteSerilizer,
                          ShiftQualificationSerializer, ShiftSerializer,
                          ShiftSkillsSerializer, QuickQuoteSerializer)


class EventTypeViewSet(viewsets.ModelViewSet):
    """ Viewset for Event Type
    """
    queryset = EventType.objects.all().order_by("-created")
    serializer_class = EventTypeSerializer


class EventViewSet(MethodSerializerMixin, viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by('-created')
    serializer_class = EventSerializer
    filter_backends = (
        filters.OrderingFilter, filters.SearchFilter, DjangoFilterBackend
    )
    ordering_fields = (
        'id', 'name', 'event_type__name', 'status',
        'client__company_name', 'start_date', 'end_date',
        'cost', 'po_number',
    )
    search_fields = ('name', )
    filter_class = EventFilter
    method_serializer_classes = {
        ('GET', ): EventSerializer,
        ('PUT', 'PATCH', 'POST'): EventCreateSerializer,
    }

    def get_serializer_class(self):
        if self.request is not None:
            if self.request.GET.get('lite', None):
                return EventLiteSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        events = Event.objects.all().order_by('-created')
        if self.action == 'list':
            events = Event.objects.ex_archived()
        if self.request.GET.get('archived') in ('true', 'True'):
            events = Event.objects.get_archived()
        if(self.request.user.user_type == User.CREW_MANAGER):
            manager_events = Shift.objects.filter(
                crew_manager__user=self.request.user).values_list(
                'event', flat=True).distinct()
            events = events.filter(id__in=manager_events)
        elif(self.request.user.user_type == User.CLIENT):
            events = events.filter(client__user=self.request.user)
        elif(self.request.user.user_type == User.SUPPLIER):
            pass

        if self.request.GET.get('month'):
            if(self.request.user.user_type == User.CREW_MANAGER):
                manager_events = Shift.objects.filter(
                    crew_manager__user=self.request.user).values_list(
                    'event', flat=True).distinct()

                events = events.filter(
                    Q(start_date__month=self.request.GET.get('month')) | Q(
                        end_date__month=self.request.GET.get('month')),
                    status=Event.CONFIRMATION,
                    id__in=manager_events,
                )
            else:
                events = events.filter(
                    Q(start_date__month__lte=self.request.GET.get('month')) | Q(
                        end_date__month__gte=self.request.GET.get('month')),
                    status=Event.CONFIRMATION
                )
            return events
        return events

    def create(self, request, *args, **kwargs):
        _data = request.data.copy()
        _data['status'] = get_event_shift_status(self, request)
        serializer = self.get_serializer(data=_data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        time = f"{datetime.now()}"
        if request.data.get('status'):
            if request.data['status'] == Event.QUOTATION:
                supplier = Suppliers.objects.get(id=request.tenant.id)
                user = User.objects.filter(user_type=User.ASSOCIATE_USER)
                NoticeType.create(f"quotation_{instance.id}_{time[5:-7]}", _(
                    instance.name), _(instance.name + " has been changed to quotation"))
                send(user, f"quotation_{instance.id}_{time[5:-7]}", {
                     "from_user": settings.DEFAULT_FROM_EMAIL})
            if request.data['status'] == Event.CONFIRMATION:
                NoticeType.create(f"confirmation_{instance.id}_{time[5:-7]}", _(
                    instance.name), _(instance.name + " has been changed to confirmation"))
                send([instance.client.user], f"confirmation_{instance.id}_{time[5:-7]}",
                     {"from_user": settings.DEFAULT_FROM_EMAIL})
        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    def get_event_status(self, request):
        """ this function return the event status according
            to the logged in user
        """
        if request.user.user_type == User.CLIENT:
            return Event.ESTIMATION
        elif request.user.user_type == User.SUPPLIER:
            return Event.QUOTATION


class EventChangeStatusView(generics.UpdateAPIView):
    """ Update view to change only the status of the Event.
        :method: `PATCH`
        :api: `events/change-event-status/<int:pk>`

        :USECASE: Used to change Event status,
    """

    queryset = Event.objects.all()
    serializer_class = EventStatusSerializer

    def get_queryset(self):
        return super().get_queryset()

    def check_permissions(self, request):
        # TODO chechk permissions of the user to change the status
        return super().check_permissions(request)

    def put(self, request, *args, **kwargs):
        return self.patch(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        # partial is set to True for PATCH, TODO disable PUT
        partial = True
        instance = self.get_object()
        cur_status = instance.status
        # FIXME check conditions for event status when they are ongoing ie, greater than confirmation
        new_status = request.data.get('status', None)
        if not new_status:
            raise exceptions.ValidationError()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        #  Update shift status
        shifts = Shift.objects.filter(event=instance, status=cur_status)
        shifts.update(status=new_status)
        self.perform_update(serializer)
        send_event_status_notification(instance, request)

        # TODO send notifications web/mob
        return Response(serializer.data)


class CrewSheduledEventListView(generics.ListAPIView):
    """ View to get List of Events for a Crew memeber for which the
        CrewMember has a accepted scheduled Shift
        :API: ``
        :method: `GET`
        :params: `crew`
        :USECASE: NOT IN USE FIXME USE in Mob
    """

    serializer_class = EventLiteSerializer

    def get_queryset(self):
        _crew = self.request.GET.get('crew', None)
        if _crew:
            qs = Event.objects.filter(
                shift__schedule__crew__id=_crew,
                shift__schedule__is_accepted=True).distinct()
        else:
            raise exceptions.ValidationError('crew is a required field')
        return qs


class CrewEventListView(generics.ListAPIView):
    """ View to get events list assigned to a crew.
        List of events taken according to Timesheet Entry
        :params: crew
        :method: GET/
        :api: events/get-crew-event-list/

        :USECASE: used in feedback filters (Web)
    """
    serializer_class = EventLiteSerializer

    def get_queryset(self):
        _crew = self.request.GET.get('crew', None)
        if _crew:
            qs = Event.objects.filter(
                shift__timesheet__crew__id=_crew).distinct()
        else:
            raise AssertionError('crew missing')
        return qs


class ShiftViewSet(viewsets.ModelViewSet):
    """
    """
    queryset = Shift.objects.all().order_by('-created')
    serializer_class = ShiftSerializer
    filter_backends = (filters.SearchFilter, DjangoFilterBackend,
                       filters.OrderingFilter)
    search_fields = ('event__name', 'id', 'name')
    # filterset_fields = ['id', 'name', 'event', 'location', ]
    ordering_fields = ('name', 'event', 'start_date', 'total_hours', 'status')
    filter_class = ShiftFilter

    def get_serializer_class(self):
        if self.request is not None:
            if self.request.GET.get('lite', None):
                return ShiftLiteSerilizer
            else:
                return ShiftSerializer
        else:
            return ShiftSerializer

    def create(self, request, *args, **kwargs):
        # TODO Optimize this function 1. Async Tasks 2.Break up into functions
        equipments = request.data['equipment']
        # FIXME Check use of Qualification
        qualifications = request.data['qualification']
        skills_list = request.data['skills_list']
        _data = request.data.copy()
        _data['status'] = get_event_shift_status(self, request)
        serializer = self.get_serializer(data=_data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        # TODO change to function in utils
        for qualification in skills_list:
            qual = Qualification.objects.get(id=qualification['id'])
            shift_qual, created = ShiftQualification.objects.get_or_create(
                shift=instance, qualification=qual
            )
            shift_qual.no_of_resources = qualification['count']
            shift_qual.save()
        for equipment in equipments:
            e = Equipments.objects.get(id=equipment['id'])
            shift_equipment, created = ShiftEquipment.objects.get_or_create(
                shift=instance, equipment=e
            )
            shift_equipment.count = equipment['count']
            shift_equipment.save()
        headers = self.get_success_headers(serializer.data)
        if request.data['repeat_shift'] is True:
            for st_date in request.data['dates_data']:
                request.data['start_date'] = st_date
                request.data['end_date'] = add_hours(
                    st_date, instance.total_shift_hours)
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                created_shift = serializer.save()

                for qualification in skills_list:
                    qual = Qualification.objects.get(id=qualification['id'])
                    shift_qual, created = ShiftQualification.objects.get_or_create(
                        shift=created_shift, qualification=qual
                    )
                    shift_qual.no_of_resources = qualification['count']
                    shift_qual.save()

                for equipment in equipments:
                    e = Equipments.objects.get(id=equipment['id'])
                    shift_equipment, created = ShiftEquipment.objects.get_or_create(
                        shift=created_shift, equipment=e
                    )
                    shift_equipment.count = equipment['count']
                    shift_equipment.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        equipments = request.data['equipment']
        # FIXME Qualification no longer used
        shift_qualifications = request.data['qualification']
        skills_list = request.data['skills_list']
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        equipment_ids = []
        curr_equips = ShiftEquipment.objects.filter(
            shift=instance).values_list('equipment__id', flat=True)
        for equipment in equipments:
            e = Equipments.objects.get(id=equipment['id'])
            shift_equipment, created = ShiftEquipment.objects.get_or_create(
                shift=instance, equipment=e
            )
            shift_equipment.count = equipment['count']
            shift_equipment.save()
            equipment_ids.append(shift_equipment.equipment.id)
        diff = list(set(curr_equips) - set(equipment_ids))
        ShiftEquipment.objects.filter(
            shift=instance, equipment__id__in=diff).delete()
        # FIXME Qualifications removed on edit should be fixed ASAP!

        curr_quali = ShiftQualification.objects.filter(
            shift=instance).values_list('qualification__id', flat=True)
        quali_ids = []
        for qualification in skills_list:
            qual = Qualification.objects.get(id=qualification['id'])
            shift_qual, created = ShiftQualification.objects.get_or_create(
                shift=instance, qualification=qual
            )
            shift_qual.no_of_resources = qualification['count']
            shift_qual.save()
            quali_ids.append(shift_qual.qualification.id)

        diff = list(set(curr_quali) - set(quali_ids))
        ShiftQualification.objects.filter(
            shift=instance, qualification__id__in=diff).delete()

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    def perform_update(self, serializer):
        serializer.save()

    def get_queryset(self):
        if self.request.user.user_type == User.CREW_MANAGER:
            queryset = Shift.objects.filter(
                crew_manager__user=self.request.user).order_by('-created')
        else:
            queryset = Shift.objects.all().order_by('-created')
        return queryset


class ShiftCrewApiview(viewsets.ModelViewSet):
    queryset = CrewProfile.objects.all()
    serializer_class = ShiftCrewSerilaizer

    def list(self, request, *args, **kwargs):
        try:
            shift = Shift.objects.filter(id=request.GET.get('shift'))
            queryset = CrewProfile.objects.filter(id__in=shift)
            queryset = queryset.order_by('-created')
            if 'search' in request.GET and request.GET.get('search') is not '':
                queryset = queryset.filter(
                    name__icontains=request.GET['search'])

            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(
                    page, context={'request': request}, many=True)
                return self.get_paginated_response(serializer.data)
            serializer = self.get_serializer(
                queryset, context={'request': request}, many=True)
            return Response(serializer.data)
        except Shift.DoesNotExist:
            raise Http404


class ShiftSkillsApiView(APIView):

    def get_object(self, pk):
        try:
            return Shift.objects.get(pk=pk)
        except Shift.DoesNotExist:
            raise Http404

    def get(self, request, pk, format=None):
        shift = self.get_object(pk)
        if shift:
            subskills = shift.skills.filter(
                parent__isnull=False).values_list('id', flat=True)
            serializer = ShiftSkillsSerializer(
                shift.skills.filter(parent__isnull=True), context={'request': request, 'subskills': subskills}, many=True
            )
            return Response(serializer.data)
        raise ParseError("No such Shift")

    def post(self, request, format=None):
        shift = self.get_object(request.data['shift_id'])
        subskills_list = []
        if shift:
            skills_id = [skill['id'] for skill in request.data['skills']]
            skills = Skills.objects.filter(id__in=skills_id)
            if skills:
                shift.skills.clear()
                shift.save()
            shift.skills.add(*skills)
            shift.save()
            for skill in request.data['skills']:
                if skill.get('subskills') and len(skill['subskills']) > 0:
                    for subskill in skill['subskills']:
                        if subskill.get('checked'):
                            subskills_list.append(subskill['id'])
            if subskills_list:
                sub_skills = Skills.objects.filter(id__in=subskills_list)
                shift.skills.add(*sub_skills)
                shift.save()
            return Response(status=status.HTTP_200_OK)
        raise ParseError("No such Shift")


class ShiftEquipmentViewSet(viewsets.ModelViewSet):
    queryset = ShiftEquipment.objects.all()
    serializer_class = ShiftEquipmentSerializer


class ShiftQualificationViewSet(viewsets.ModelViewSet):
    queryset = ShiftQualification.objects.all()
    serializer_class = ShiftQualificationSerializer


def get_next_n_days(start_date, no_of_days):
    days = []
    for i in range(0, no_of_days):
        days.append(start_date + timedelta(days=i))
    return days


class ShiftScheduleViewSet(viewsets.ModelViewSet):
    queryset = Shift.objects.all()
    serializer_class = ShiftSerializer

    def get_queryset(self):
        # Quering Shifts based on local TimeZone coming from Request
        if self.request.user.user_type == User.CREW_MANAGER:
            shift_queryset = Shift.objects.filter(
                crew_manager__user=self.request.user, status=Shift.CONFIRMATION)
        else:
            shift_queryset = Shift.objects.filter(status=Shift.CONFIRMATION)
        if self.request.GET.get('start_date') and self.request.GET.get('end_date'):
            # tz_offset = int(self.request.GET.get('tz_offset'))
            tz_offset = self.request.GET.get('tz_offset')
            # if(tz_offset < 0):
            #     qs = shift_queryset.filter(event__id=self.request.GET.get('event_id')).annotate(
            #         start_date_local=ExpressionWrapper(F('start_date__date') + timedelta(minutes=abs(tz_offset)),
            #                                            output_field=DateTimeField()))
            # elif(tz_offset > 0):
            #     qs = shift_queryset.filter(event__id=self.request.GET.get('event_id')).annotate(
            #         start_date_local=ExpressionWrapper(F('start_date__date') - timedelta(minutes=abs(tz_offset)),
            #                                            output_field=DateTimeField()))
            # else:
            queryset = shift_queryset.filter(
                event__id=self.request.GET.get('event_id'),
                start_date__date__range=[make_aware(datetime.strptime(
                    self.request.GET.get('start_date'), "%Y-%m-%d")), make_aware(datetime.strptime(
                        self.request.GET.get('end_date'), "%Y-%m-%d"))]
            )
            return queryset
            # print(qs,"========================!!!!!!!!")
            # queryset = qs.filter(start_date_local__date__range=[self.request.GET.get(
            #     'start_date'), self.request.GET.get('end_date')])
        else:
            queryset = shift_queryset.filter(
                event__id=self.request.GET.get('event_id')
            )
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        import pytz
        tz_offset = self.request.GET.get('tz_offset')
        tz = pytz.timezone(tz_offset)
        start_date = make_aware(datetime.strptime(
            self.request.GET.get('start_date'), "%Y-%m-%d"), tz)
        end_date = make_aware(datetime.strptime(
            self.request.GET.get('end_date'), "%Y-%m-%d"), tz)
        days = get_next_n_days(start_date, (end_date - start_date).days)
        data = []
        for day in days:
            # start_date = day + timedelta(minutes=tz_offset)
            start_date = day
            end_date = start_date + timedelta(days=1)
            serializer = self.get_serializer(
                queryset.filter(start_date__range=[start_date, end_date]), many=True)
            data.append({
                "day": day,
                "shifts": serializer.data
            })
        return Response(data)


class ScheduleAllEvents(viewsets.ModelViewSet):
    queryset = Event.objects.all().order_by('-created')
    serializer_class = EventSerializer
    paginator = None

    # def get_queryset(self):
    #     if self.request.GET.get('start_date') and self.request.GET.get('end_date'):
    #         return Event.objects.filter(
    #             Q(start_date__date__range=[self.request.GET.get('start_date'), self.request.GET.get('end_date')])|
    #             Q(end_date__date__range=[self.request.GET.get('start_date'), self.request.GET.get('end_date')])
    #             )
    #     return Event.objects.all().order_by('-created')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        start_date = datetime.strptime(
            self.request.GET.get('start_date'), "%Y-%m-%d")
        end_date = datetime.strptime(
            self.request.GET.get('end_date'), "%Y-%m-%d")
        days = get_next_n_days(start_date, (end_date - start_date).days)
        data = []
        for day in days:
            queryset_1 = queryset.filter(start_date__date__lte=day)
            queryset_2 = queryset.filter(end_date__date__gte=day)
            self.request.parser_context['day'] = day
            serializer = self.get_serializer((queryset_1 & queryset_2).distinct(
            ), many=True, context={'request': self.request, 'day': day})
            data.append({
                "day": day,
                "events": serializer.data
            })
        return Response(data)


class CrewShiftListAPIView(ListAPIView):
    """ Returns a list of shifts assinged to a crew(user)
        :api: get-crew-shift-list/
    """
    serializer_class = ShiftCrewListingSerilizer
    permission_classes = [IsAuthenticated]
    filter_backends = (filters.SearchFilter, DjangoFilterBackend,
                       filters.OrderingFilter)
    ordering_fields = ('id', 'name', 'start_date', 'end_date',
                       'total_shift_hours', )
    search_fields = ('name', )
    filter_class = ShiftFilter

    def get_queryset(self):
        if self.request.GET.get('user'):
            queryset = Shift.objects.filter(
                schedule__crew__user=self.request.GET.get('user'), schedule__is_scheduled=True)
            queryset = self.get_filtered_qs(
                queryset, self.request.GET.get('user'))
        else:
            queryset = Shift.objects.filter(
                schedule__crew__user=self.request.user.id, schedule__is_scheduled=True)
            queryset = self.get_filtered_qs(queryset, self.request.user.id)
        return queryset

    def get_serializer_context(self):
        if self.request.GET.get('user'):
            _id = self.request.GET.get('user')
        else:
            _id = self.request.user.id
        return {'user': _id}

    def get_filtered_qs(self, queryset, user):
        ''' additional filters to filter the queryset according to params
        '''
        if self.request.GET.get('pending') in ('True', 'true'):
            queryset = Shift.objects.filter(
                schedule__crew__user=user,
                schedule__is_scheduled=True, schedule__is_accepted=False,
                schedule__is_rejected=False)
        if self.request.GET.get('accepted') in ('True', 'true'):
            queryset = Shift.objects.filter(
                schedule__crew__user=user,
                schedule__is_scheduled=True, schedule__is_accepted=True,
                schedule__is_rejected=False)
        return queryset


class CrewShiftRetrieveAPIView(RetrieveAPIView):
    """ Returns a detail of shift assinged to a crew(user)
    """
    serializer_class = ShiftCrewDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.GET.get('user'):
            queryset = Shift.objects.filter(
                schedule__crew__user=self.request.GET.get('user'), schedule__is_scheduled=True)
        else:
            queryset = Shift.objects.filter(
                schedule__crew__user=self.request.user.id, schedule__is_scheduled=True)
        return queryset

    def get_serializer_context(self):
        if self.request.GET.get('user'):
            _id = self.request.GET.get('user')
        else:
            _id = self.request.user.id
        return {'user': _id}


class ShiftCrewListAPI(APIView):
    """ API to list crew members assigned to a shift
        :API: get-assigned-shift-crew/
    """

    def get(self, request):
        event = self.request.GET.get('event', None)
        shift = self.request.GET.get('shift', None)

        if event:
            shifts = Shift.objects.filter(event=event)
            ser = ShiftLiteSerilizer(shifts, many=True)
            return Response(ser.data)

        elif shift:
            crews = Schedule.objects.filter(shift=shift, is_scheduled=True, is_accepted=True).values_list(
                'crew__id', flat=True)
            ser = CrewProfileLiteSerializer(
                CrewProfile.objects.filter(id__in=crews), many=True)
            return Response(ser.data)


class UpcomingShiftView(APIView):
    """ View to get Upcoming/Current shift of a logged in Crew Member
        :API: get-upcoming-shift/
        :METHOD: GET
        :FIXME: get next shift if current running shift is clocked out.
        check TODO
    """

    def get(self, request):
        if request.user.user_type == User.CREW_MEMBER:
            queryset = Shift.objects.filter(
                schedule__crew__user=self.request.user.id,
                schedule__is_scheduled=True,
                schedule__is_accepted=True
            )
            # TODO exclude completed timesheets if needed
            # timesheets = TimeSheet.objects.filter(
            #     crew__user=self.request.user,
            #     clock_in__isnull=False,
            #     clock_out__isnull=False
            # ).values_list('shift', flat=True).distinct()
            shift = queryset.filter(
                Q(start_date__gte=timezone.now()) | Q(
                    end_date__gte=timezone.now())
            ).order_by('start_date').first()
            if shift:
                ser = ShiftCrewDetailSerilizer(
                    shift,
                    context={"user": request.user.id}
                )
                return Response(ser.data, status=status.HTTP_200_OK)
            else:
                return Response({'detail': 'No-upcoming Shifts'}, status=status.HTTP_404_NOT_FOUND)
        else:
            return Response({'error': 'bad-request'}, status=status.HTTP_400_BAD_REQUEST)


class UpcomingAllShiftView(generics.ListAPIView):
    """ View to get all Upcoming/Current shift of a logged in Crew Member
        :API: get-all-upcoming-shift/
        :METHOD: GET
    """
    serializer_class = ShiftCrewListingSerilizer
    permission_class = (IsAuthenticated)

    def get_queryset(self):
        if self.request.user.user_type == User.CREW_MEMBER:
            queryset = Shift.objects.filter(
                schedule__crew__user=self.request.user.id,
                schedule__is_scheduled=True,
                schedule__is_accepted=True
            )
            shifts = queryset.filter(
                Q(start_date__gte=timezone.now()) | Q(
                    end_date__gte=timezone.now())
            ).order_by('start_date')
        else:
            raise exceptions.ValidationError("View allowed only for Memeber")
        return shifts

    def get_serializer_context(self):
        context = {
            "user": self.request.user.id
        }
        return context


class ChangeShiftStatusView(APIView):
    """ View to change status of a list of shifts or bulk change to new status
        :api: `/events/change-shift-status`
        :params: `shifts` or `cur_status`, `new_status`
        :method: `POST`
    """

    def post(self, request):
        _shifts = self.request.data.get('shifts', None)
        _cur_status = self.request.data.get('cur_status', None)
        _new_status = self.request.data.get('new_status', None)
        _event = self.request.data.get('event', None)
        if not (_shifts or _cur_status) and not _new_status and not _event:
            raise exceptions.ValidationError('params missing')
        else:
            # change shifts status to new status
            if _cur_status:
                shifts = Shift.objects.filter(event=_event, status=_cur_status)
                shifts.update(status=_new_status)
            elif _shifts:
                shifts = Shift.objects.filter(event=_event, id__in=_shifts)
                shifts.update(status=_new_status)
            # update event status to the highest shift status
            _status = update_event_status_from_shift(_event)
            return Response(
                {'detail': 'shifts status updated',
                 'event_status': _status},
                status=status.HTTP_200_OK
            )


class QuickQuoteViewSet(viewsets.ModelViewSet):
    queryset = QuickQuote.objects.all().order_by('-created')
    serializer_class = QuickQuoteSerializer
    filter_backends = (filters.SearchFilter, DjangoFilterBackend,
                       filters.OrderingFilter)
    ordering_fields = ('email', 'created', 'first_name', 'last_name')
    search_fields = ('first_name', 'last_name', 'phone', 'email')


class ShiftHistoryViewSet(APIView):
    """ View to get history of shifts of a crew member
        (currently for supplier login)
        :API: shift-history/<int:pk>
        :METHOD: GET
    """

    def get(self, request, pk):
        shift_queryset = Shift.objects.filter(
            schedule__crew__id=pk,
            schedule__is_scheduled=True,
            schedule__is_accepted=True
        )
        shifts = shift_queryset.filter(
            end_date__lte=timezone.now()
        ).order_by('end_date').first()
        if shifts:
            ser = ShiftCrewDetailSerilizer(
                shifts, context={"user": pk}
            )
            return Response(ser.data, status=status.HTTP_200_OK)
        else:
            return Response({'detail': 'No Previous Shifts'}, status=status.HTTP_404_NOT_FOUND)
