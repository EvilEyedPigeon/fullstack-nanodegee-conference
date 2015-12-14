#!/usr/bin/env python

"""models.py

Udacity conference server-side Python App Engine data & ProtoRPC models

$Id: models.py,v 1.1 2014/05/24 22:01:10 wesc Exp $

created/forked from conferences.py by wesc on 2014 may 24

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

import httplib
import endpoints
from protorpc import messages
from google.appengine.ext import ndb

class ConflictException(endpoints.ServiceException):
    """ConflictException -- exception mapped to HTTP 409 response"""
    http_status = httplib.CONFLICT

class Profile(ndb.Model):
    """Profile -- User profile object"""
    displayName = ndb.StringProperty()
    mainEmail = ndb.StringProperty()
    teeShirtSize = ndb.StringProperty(default='NOT_SPECIFIED')
    conferenceKeysToAttend = ndb.StringProperty(repeated=True)
    sessionKeysInWishlist = ndb.KeyProperty(kind='Session', repeated=True)

class ProfileMiniForm(messages.Message):
    """ProfileMiniForm -- update Profile form message"""
    displayName = messages.StringField(1)
    teeShirtSize = messages.EnumField('TeeShirtSize', 2)

class ProfileForm(messages.Message):
    """ProfileForm -- Profile outbound form message"""
    displayName = messages.StringField(1)
    mainEmail = messages.StringField(2)
    teeShirtSize = messages.EnumField('TeeShirtSize', 3)
    conferenceKeysToAttend = messages.StringField(4, repeated=True)
    sessionKeysInWishlist = messages.StringField(5, repeated=True)

class StringMessage(messages.Message):
    """StringMessage-- outbound (single) string message"""
    data = messages.StringField(1, required=True)

class BooleanMessage(messages.Message):
    """BooleanMessage-- outbound Boolean value message"""
    data = messages.BooleanField(1)

class Conference(ndb.Model):
    """Conference -- Conference object"""
    name            = ndb.StringProperty(required=True)
    description     = ndb.StringProperty()
    organizerUserId = ndb.StringProperty()
    topics          = ndb.StringProperty(repeated=True)
    city            = ndb.StringProperty()
    startDate       = ndb.DateProperty()
    month           = ndb.IntegerProperty() # TODO: do we need for indexing like Java?
    endDate         = ndb.DateProperty()
    maxAttendees    = ndb.IntegerProperty()
    seatsAvailable  = ndb.IntegerProperty()

class ConferenceForm(messages.Message):
    """ConferenceForm -- Conference outbound form message"""
    name            = messages.StringField(1)
    description     = messages.StringField(2)
    organizerUserId = messages.StringField(3)
    topics          = messages.StringField(4, repeated=True)
    city            = messages.StringField(5)
    startDate       = messages.StringField(6) #DateTimeField()
    month           = messages.IntegerField(7)
    maxAttendees    = messages.IntegerField(8)
    seatsAvailable  = messages.IntegerField(9)
    endDate         = messages.StringField(10) #DateTimeField()
    websafeKey      = messages.StringField(11)
    organizerDisplayName = messages.StringField(12)

class ConferenceForms(messages.Message):
    """ConferenceForms -- multiple Conference outbound form message"""
    items = messages.MessageField(ConferenceForm, 1, repeated=True)

class Session(ndb.Model):
    """Session -- Session object"""
    name               = ndb.StringProperty(required=True)
    typeOfSession      = ndb.StringProperty(required=True)
    highlights         = ndb.StringProperty(repeated=True)
    speakerWebSafeKeys = ndb.StringProperty(repeated=True)
    duration           = ndb.IntegerProperty()  # In minutes
    date               = ndb.DateProperty()
    startTime          = ndb.TimeProperty()

class SessionForm(messages.Message):
    """Session -- Session form message"""
    name               = messages.StringField(1)
    typeOfSession      = messages.StringField(2)
    highlights         = messages.StringField(3, repeated=True)
    confWebsafeKey     = messages.StringField(4)
    speakerWebSafeKeys = messages.StringField(5, repeated=True)
    duration           = messages.IntegerField(6)
    date               = messages.StringField(7)  # DateTimeField()
    startTime          = messages.StringField(8)  # DateTimeField()
    websafeKey         = messages.StringField(9)

class SessionForms(messages.Message):
    """SessionForms -- multiple Session outbound form message"""
    items = messages.MessageField(SessionForm, 1, repeated=True)

class Speaker(ndb.Model):
    """Speaker -- Speaker object"""
    name            = ndb.StringProperty(required=True)
    organization    = ndb.StringProperty()
    email           = ndb.StringProperty()
    website         = ndb.StringProperty()

class SpeakerForm(messages.Message):
    """Speaker -- Speaker form message"""
    name            = messages.StringField(1)
    organization    = messages.StringField(2)
    email           = messages.StringField(3)
    website         = messages.StringField(4)
    websafeKey      = messages.StringField(5)

class SpeakerForms(messages.Message):
    """SpeakerForms - multiple Speaker outbound form message"""
    items = messages.MessageField(SpeakerForm, 1, repeated=True)

class TeeShirtSize(messages.Enum):
    """TeeShirtSize -- t-shirt size enumeration value"""
    NOT_SPECIFIED = 1
    XS_M = 2
    XS_W = 3
    S_M = 4
    S_W = 5
    M_M = 6
    M_W = 7
    L_M = 8
    L_W = 9
    XL_M = 10
    XL_W = 11
    XXL_M = 12
    XXL_W = 13
    XXXL_M = 14
    XXXL_W = 15

class ConferenceQueryForm(messages.Message):
    """ConferenceQueryForm -- Conference query inbound form message"""
    field = messages.StringField(1)
    operator = messages.StringField(2)
    value = messages.StringField(3)

class ConferenceQueryForms(messages.Message):
    """ConferenceQueryForms -- multiple ConferenceQueryForm inbound form message"""
    filters = messages.MessageField(ConferenceQueryForm, 1, repeated=True)

class SessionQueryDurationForm(messages.Message):
    """SessionQueryDuration - Session duration query inbound message"""
    minDuration = messages.IntegerField(1)
    maxDuration = messages.IntegerField(2)

class SpeakerQueryOrganizationForm(messages.Message):
    """SpeakerQueryOrganizationForm -- Speaker organization query inbound message"""
    organization = messages.StringField(1)
