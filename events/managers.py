# TODO create managers for Shifts
from django.db import models


class EventQuerySet(models.QuerySet):
    """ Querset for Events
    """

    def get_archived(self):
        return self.filter(is_archived=True)

    def ex_archived(self):
        return self.exclude(is_archived=True)


class EventManager(models.Manager):
    """ Manager for Events Models
        `get_archived` returns archived objects
        `ex_archived` returns non-archived objects
    """

    def get_queryset(self):
        return super().get_queryset()

    def get_custm_queryset(self):
        # for evry other custom query
        return EventQuerySet(self.model, using=self._db)

    def get_archived(self):
        # get only archived objects
        return self.get_custm_queryset().get_archived()

    def ex_archived(self):
        # get evry thing
        return self.get_custm_queryset().ex_archived()
