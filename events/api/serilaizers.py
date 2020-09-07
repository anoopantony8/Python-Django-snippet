from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.api.serializers import (CustomUserModelSerializer,
                                           ProfileSkillsSerializer)
from apps.accounts.models import (CrewProfile, User, UserQualification,
                                  UserSkills)
from apps.common.api.serializers import (CrewDepartmentSerializer,
                                         EquipmentSerializer,
                                         LocationSerializer,
                                         QualificationLiteSerialiser,
                                         QualificationSerializer,
                                         SkillsSerializer)
from apps.common.models import Location, Skills
from apps.events.choices import EVENT_STATUS, STATUS
from apps.events.models import (Event, EventType, Shift, ShiftEquipment,
                                ShiftQualification, QuickQuote)
from apps.scheduler.models import Schedule
from apps.timesheet.models import TimeSheet


class EventTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventType
        fields = '__all__'


class EventSerializer(serializers.ModelSerializer):
    event_type_name = serializers.SerializerMethodField('make_event_type')
    status_name = serializers.SerializerMethodField('make_status')
    client_name = serializers.SerializerMethodField('make_client')
    location_details = serializers.SerializerMethodField()
    total_no_of_shifts = serializers.SerializerMethodField()

    def make_event_type(self, obj):
        if obj.event_type:
            return obj.event_type.name
        return None

    def make_client(self, obj):
        if obj.client:
            return obj.client.company_name
        return None

    def get_location_details(self, obj):
        return LocationSerializer(obj.location, many=True).data

    def make_status(self, obj):
        status = dict(EVENT_STATUS)
        return status[obj.status]

    def get_total_no_of_shifts(self, obj):
        if self.context['request'].parser_context.get('day'):
            return Shift.objects.filter(
                Q(event=obj),
                Q(start_date__date=self.context['request'].parser_context['day']) | Q(end_date__date=self.context['request'].parser_context['day'])).count()
        return Shift.objects.filter(event__id=obj.id, status=Shift.CONFIRMATION).count()

    class Meta:
        model = Event
        fields = '__all__'


class EventCreateSerializer(serializers.ModelSerializer):
    location_details = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ('__all__')

    def get_location_details(self, obj):
        return LocationSerializer(obj.location, many=True).data

    def validate_location(self, data):
        if self.instance and data != self.instance.location.all():
            removed_loc = list(set(self.instance.location.all()) - set(data))
            if removed_loc:
                rel_shift = Shift.objects.filter(location__in=removed_loc,
                                                 event=self.instance)
                if rel_shift.exists():
                    raise serializers.ValidationError(
                        f"{rel_shift.count()} shift related to the location's removed.")
        return data


class EventLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ('id', 'name')


class EventStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ('id', 'name', 'status')


class ShiftCrewSerilaizer(serializers.ModelSerializer):
    user = CustomUserModelSerializer()
    # skills = serializers.SerializerMethodField('make_skills')

    # def make_skills(self, obj):
    #     userskills = UserSkills.objects.filter(
    #         profile=obj, skills__parent__isnull=True
    #     ).values_list('skills__id', flat=True)
    #     profile_skills = Skills.objects.filter(id__in=userskills)
    #     serializer = ProfileSkillsSerializer(
    #         profile_skills, many=True,
    #         context={'request': self.context['request'], 'profile_obj': obj}
    #     )
    #     return serializer.data

    class Meta:
        model = CrewProfile
        fields = '__all__'


class ShiftLiteSerilizer(serializers.ModelSerializer):
    location_name = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = ('id', 'name', 'location_name', 'location',
                  'start_date', 'total_shift_hours', 'end_date')

    def get_location_name(self, obj):
        return obj.location.name


class ShiftReadOnlyLiteSerializer(serializers.ModelSerializer):
    """read-only shift serializer with minimal details about shift
    """
    event_name = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = (
            'id', 'name', 'start_date', 'total_shift_hours',
            'end_date', 'event_name', 'location_name',
        )
        read_only_fields = fields

    def get_event_name(self, obj):
        return obj.event.name

    def get_location_name(self, obj):
        return obj.location.name


class ShiftCrewListingSerilizer(serializers.ModelSerializer):
    """ Serializer to get minimal amount of info for a user about shift Lisiting
    """

    cost = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()
    schedule_details = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = ('id', 'name', 'start_date', 'end_date', 'total_shift_hours',
                  'cost', 'location_name', 'schedule_details')

    def get_cost(self, obj):
        # TODO change to a function
        qual = ShiftQualification.objects.filter(shift=obj).values_list(
            'qualification', flat=True)
        cost = UserQualification.objects.filter(profile__user=self.context['user'],
                                                qualification__in=qual).aggregate(
                                                    sum=Sum('base_pay_rate'))
        try:
            cost = cost['sum'] * obj.total_shift_hours
        except TypeError as te:
            cost = 0
        return cost

    def get_location_name(self, obj):
        return obj.location.name

    def get_schedule_details(self, obj):
        try:
            sch = Schedule.objects.get(
                shift=obj, crew__user=self.context['user'])
            data = {'is_crew_chief': sch.is_crew_chief,
                    'is_accepted': sch.is_accepted, 'is_rejected': sch.is_rejected}
        except Exception as ex:
            return 'N.A'
        return data


class ShiftCrewDetailSerilizer(serializers.ModelSerializer):
    """ Serializer to get minimal amount of info for a user about shift Lisiting
    """

    cost = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()
    event_name = serializers.SerializerMethodField()
    inprogress_shift = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = ('id', 'name', 'start_date', 'end_date', 'total_shift_hours',
                  'cost', 'location_name', 'event_name', 'inprogress_shift')
        read_only_fields = fields

    def get_cost(self, obj):
        # TODO change to a function
        qual = ShiftQualification.objects.filter(shift=obj).values_list(
            'qualification', flat=True)
        cost = UserQualification.objects.filter(profile__user=self.context['user'],
                                                qualification__in=qual).aggregate(
                                                    sum=Sum('base_pay_rate'))
        try:
            cost = cost['sum'] * obj.total_shift_hours
        except TypeError as te:
            cost = 0
        return cost

    def get_location_name(self, obj):
        return obj.location.name

    def get_event_name(self, obj):
        return obj.event.name

    def get_inprogress_shift(self, obj):
        try:
            _timesheet = TimeSheet.objects.get(shift=obj, crew__user__id=self.context['user'])
            if not _timesheet.clock_out and _timesheet.clock_in <= timezone.now():
                return {'running': True, 'timesheet_id': _timesheet.id}
        except Exception as ex:
            return {'running': False, 'timesheet_id': 'N.A'}


class ShiftCrewDetailSerializer(serializers.ModelSerializer):
    """ Serializer to get minimal amount of info for a user about shift -Detail
    """
    total_rate = serializers.SerializerMethodField()
    event_name = serializers.SerializerMethodField()
    location_name = serializers.SerializerMethodField()
    qualifications = serializers.SerializerMethodField()
    schedule_details = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = ('id', 'name', 'event', 'start_date', 'end_date', 'total_shift_hours',
                  'total_rate', 'event_name', 'location_name', 'qualifications', 'schedule_details')

    def get_total_rate(self, obj):
        # FIXME
        qual = ShiftQualification.objects.filter(shift=obj).values_list(
            'qualification', flat=True)
        cost = UserQualification.objects.filter(profile__user=self.context['user'],
                                                qualification__in=qual).aggregate(
                                                    sum=Sum('base_pay_rate'))
        cost = cost['sum'] * obj.total_shift_hours
        return cost

    def get_event_name(self, obj):
        return obj.event.name

    def get_location_name(self, obj):
        return obj.location.name

    def get_qualifications(self, obj):
        shift_qualifications = ShiftQualification.objects.filter(shift=obj)
        qual = ShiftQualificationSerializer(shift_qualifications, many=True)
        return qual.data

    def get_schedule_details(self, obj):
        try:
            sch = Schedule.objects.get(
                shift=obj, crew__user=self.context['user'])
            data = {'is_crew_chief': sch.is_crew_chief,
                    'is_accepted': sch.is_accepted, 'is_rejected': sch.is_rejected}
        except Exception as ex:
            return 'N.A'
        return data


class ShiftEquipmentSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField('make_name')
    charge_rate = serializers.SerializerMethodField()

    def make_name(self, obj):
        return obj.equipment.name

    def get_charge_rate(self, obj):
        return obj.equipment.charge_rate

    class Meta:
        model = ShiftEquipment
        fields = '__all__'


class ShiftQualificationSerializer(serializers.ModelSerializer):
    qualification_details = serializers.SerializerMethodField()

    class Meta:
        model = ShiftQualification
        fields = '__all__'

    def get_qualification_details(self, obj):
        return QualificationLiteSerialiser(obj.qualification).data


class ShiftSerializer(serializers.ModelSerializer):
    location_name = serializers.SerializerMethodField()
    department_details = serializers.SerializerMethodField()
    manager_name = serializers.SerializerMethodField()
    skills = SkillsSerializer(many=True, required=False)
    qualifications = serializers.SerializerMethodField()
    equipment_details = serializers.SerializerMethodField()
    event_name = serializers.SerializerMethodField()
    actions_needed = serializers.SerializerMethodField()

    def get_actions_needed(self, obj):
        assigned = Schedule.objects.filter(
            shift=obj, is_scheduled=True).count()
        accepted = Schedule.objects.filter(
            shift=obj, is_scheduled=True, is_accepted=True).count()
        actions = int(obj.no_of_resources - accepted)
        rejected = Schedule.objects.filter(
            shift=obj, is_scheduled=True, is_rejected=True).count()
        crew_chief_assigned = Schedule.objects.filter(shift=obj, is_scheduled=True,
                                                      is_crew_chief=True).count()
        crew_chief_names = Schedule.objects.filter(
            shift=obj, is_scheduled=True, is_crew_chief=True
            ).values_list('crew__user__first_name')
        crew_chief_accepted = Schedule.objects.filter(shift=obj, is_scheduled=True,
                                                      is_crew_chief=True, is_accepted=True).count()
        crew_chief_rejected = Schedule.objects.filter(shift=obj, is_scheduled=True,
                                                      is_crew_chief=True, is_rejected=True).count()
        return {"assigned": assigned, "actions": actions, "accepted": accepted,
                "rejected": rejected,
                "crew_chief": {
                    "crew_chief_assigned": crew_chief_assigned,
                    "crew_chief_accepted": crew_chief_accepted,
                    "crew_chief_rejected": crew_chief_rejected,
                    "crew_chief_names": crew_chief_names
                    }
                }

    def get_location_name(self, obj):
        if obj.location:
            return obj.location.name
        return None

    def get_department_details(self, obj):
        if obj.department:
            return CrewDepartmentSerializer(obj.department).data
        return None

    def get_manager_name(self, obj):
        if obj.crew_manager:
            return f'{obj.crew_manager.user.first_name} {obj.crew_manager.user.last_name}'
        return None

    def get_qualifications(self, obj):
        shift_qualifications = ShiftQualification.objects.filter(shift=obj)
        qual = ShiftQualificationSerializer(shift_qualifications, many=True)
        return qual.data

    def get_equipment_details(self, obj):
        shift_equipment = ShiftEquipment.objects.filter(shift=obj)
        return ShiftEquipmentSerializer(shift_equipment, many=True).data

    def get_event_name(self, obj):
        return obj.event.name

    class Meta:
        model = Shift
        fields = '__all__'


class ShiftScheduleSerializer(serializers.ModelSerializer):
    # TODO duplicate serializer optimise this
    location_name = serializers.SerializerMethodField()
    department_details = serializers.SerializerMethodField()
    manager_name = serializers.SerializerMethodField()
    skills = SkillsSerializer(many=True, required=False)
    qualifications = serializers.SerializerMethodField()
    equipment_details = serializers.SerializerMethodField()
    event_name = serializers.SerializerMethodField()
    actions_needed = serializers.SerializerMethodField()

    def get_actions_needed(self, obj):
        assigned = Schedule.objects.filter(
            shift=obj, is_scheduled=True).count()
        accepted = Schedule.objects.filter(
            shift=obj, is_scheduled=True, is_accepted=True).count()
        actions = int(obj.no_of_resources - accepted)
        rejected = Schedule.objects.filter(
            shift=obj, is_scheduled=True, is_rejected=True).count()
        crew_chief_assigned = Schedule.objects.filter(shift=obj, is_scheduled=True,
                                                      is_crew_chief=True).count()
        crew_chief_accepted = Schedule.objects.filter(shift=obj, is_scheduled=True,
                                                      is_crew_chief=True, is_accepted=True).count()
        crew_chief_rejected = Schedule.objects.filter(shift=obj, is_scheduled=True,
                                                      is_crew_chief=True, is_rejected=True).count()
        return {"assigned": assigned, "actions": actions, "accepted": accepted,
                "rejected": rejected,
                "crew_chief": {
                    "crew_chief_assigned": crew_chief_assigned,
                    "crew_chief_accepted": crew_chief_accepted,
                    "crew_chief_rejected": crew_chief_rejected}
                }

    def get_location_name(self, obj):
        if obj.location:
            return obj.location.name
        return None

    def get_department_details(self, obj):
        if obj.department:
            return CrewDepartmentSerializer(obj.department).data
        return None

    def get_manager_name(self, obj):
        if obj.crew_manager:
            return f'{obj.crew_manager.user.first_name} {obj.crew_manager.user.last_name}'
        return None

    def get_qualifications(self, obj):
        shift_qualifications = ShiftQualification.objects.filter(shift=obj)
        qual = ShiftQualificationSerializer(shift_qualifications, many=True)
        return qual.data

    def get_equipment_details(self, obj):
        shift_equipment = ShiftEquipment.objects.filter(shift=obj)
        return ShiftEquipmentSerializer(shift_equipment, many=True).data

    def get_event_name(self, obj):
        return obj.event.name

    class Meta:
        model = Shift
        fields = '__all__'


class ChildSerializer(serializers.ModelSerializer):
    checked = serializers.BooleanField(default=False)

    class Meta:
        model = Skills
        fields = '__all__'


class ShiftSkillsSerializer(serializers.ModelSerializer):
    subskills = serializers.SerializerMethodField('make_subskills')
    # pagination_class = StandardResultsSetPagination

    def make_subskills(self, obj):
        subskills = Skills.objects.filter(
            parent=obj, id__in=self.context['subskills'])
        # ser = ChildSerializer()
        return (ChildSerializer(subskills, many=True)).data

    class Meta:
        model = Skills
        fields = '__all__'


class EventScheduleSerializer(serializers.ModelSerializer):
    shifts = serializers.SerializerMethodField()
    event_location_details = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    event_type_name = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = '__all__'

    def get_shifts(self, obj):
        shifts = Shift.objects.filter(event=obj)
        return (OrderShiftSerializer(shifts, many=True)).data

    def get_event_location_details(self, obj):
        return LocationSerializer(obj.location, many=True).data

    def get_client_name(self, obj):
        return obj.client.company_name

    def get_event_type_name(self, obj):
        if obj.event_type:
            return obj.event_type.name
        return 'N.A'


class OrderShiftSerializer(serializers.ModelSerializer):
    location_name = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    manager_name = serializers.SerializerMethodField()
    skills = SkillsSerializer(many=True, required=False)
    # qualifications = serializers.SerializerMethodField()
    equipment_details = serializers.SerializerMethodField()
    # shift_cost_details = serializers.SerializerMethodField()
    travel_expense = serializers.SerializerMethodField()
    department_location = serializers.SerializerMethodField()

    def get_location_name(self, obj):
        if obj.location:
            return obj.location.name
        return None

    def get_department_name(self, obj):
        if obj.department:
            return obj.department.name
        return None

    def get_manager_name(self, obj):
        if obj.crew_manager:
            return obj.crew_manager.user.first_name
        return None

    def get_qualifications(self, obj):
        qual = QualificationSerializer(obj.qualification, many=True)
        return qual.data

    def get_shift_cost_details(self, obj):
        # import pdb; pdb.set_trace()
        qual_cost = float(str(obj.qualification_cost()))
        equip_cost = float(str(obj.equipment_cost()))
        travel_cost = float(str(obj.get_travel_expenses()['cost']))
        total_cost = {"qualification_cost": qual_cost,
                      "equipment_cost": equip_cost,
                      "travel_cost": travel_cost,
                      }
        total = qual_cost + equip_cost + travel_cost
        return {'cost_details': total_cost, "total": total}

    def get_travel_expense(self, obj):
        return obj.get_travel_expenses()

    def get_department_location(self, obj):
        return obj.department.location.name

    def get_equipment_details(self, obj):
        shift_equipment = ShiftEquipment.objects.filter(shift=obj)
        return ShiftEquipmentSerializer(shift_equipment, many=True).data

    class Meta:
        model = Shift
        fields = '__all__'


class QuickQuoteSerializer(serializers.ModelSerializer):

    class Meta:
        model = QuickQuote
        fields = '__all__'
