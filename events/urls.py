from django.conf.urls import include, url
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.events.api import views
from apps.events.api import order_views

router = DefaultRouter()
router.register(r'event', views.EventViewSet)
# TODO change to schedule apps url
router.register(r'shift-schedule', views.ShiftScheduleViewSet)
router.register(r'event-schedule', views.ScheduleAllEvents)
router.register(r'event_types', views.EventTypeViewSet)
router.register(r'shift', views.ShiftViewSet)
router.register(r'order', order_views.OrderViewSet)
router.register(r'shift-equipment', views.ShiftEquipmentViewSet)
router.register(r'shift-qualification', views.ShiftQualificationViewSet)
router.register(r'quick-quote', views.QuickQuoteViewSet)
urlpatterns = [
    path('', include(router.urls)),
    path('add-shift-skills/', views.ShiftSkillsApiView.as_view()),
    path('get-shift-skills/<int:pk>/',
         views.ShiftSkillsApiView.as_view()),  # pk of the shift
    path('get-shift-crew/', views.ShiftCrewApiview.as_view({'get': 'list'})),
    path('get-crew-shift-list/', views.CrewShiftListAPIView.as_view()),
    path('get-crew-shift-list/<int:pk>/',
         views.CrewShiftRetrieveAPIView.as_view()),
    path('get-assigned-shift-crew/', views.ShiftCrewListAPI.as_view()),
    path('get-upcoming-shift/', views.UpcomingShiftView.as_view()),
    path('get-all-upcoming-shift/', views.UpcomingAllShiftView.as_view()),
    path('get-crew-event-list/', views.CrewEventListView.as_view()),
    path('change-event-status/<int:pk>', views.EventChangeStatusView.as_view()),
    path('change-shift-status/', views.ChangeShiftStatusView.as_view()),
    path('shift-history/<int:pk>', views.ShiftHistoryViewSet.as_view())
]
