#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import SessionQueryDurationForm
from models import Speaker
from models import SpeakerForm
from models import SpeakerForms
from models import SpeakerQueryOrganizationForm

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED_SPEAKER"
FEATURED_SPEAKER_TPL = ('The Featured Speaker is %s, who is giving the '
                        'following sessions: %s.')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = CONF_GET_REQUEST

SESSION_BY_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.StringField(2),
)

SESSION_BY_SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSpeakerKey=messages.StringField(1),
)

UPDATE_WISHLIST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""


    def _checkEntityExists(self, websafe_key, entity_kind):
        """Checks that an entity exists and returns it if it does."""
        try:
            entity = ndb.Key(urlsafe=websafe_key).get()
        except TypeError:
            raise endpoints.BadRequestException(
                'Non-string not allowed as %s websafe key: %s' %
                (entity_kind, websafe_key)
            )
        except Exception, e:
            # When deployed, we have to inspect the name of the exeption as
            # trying to catch ProtocolBuffer.ProtocolBufferDecodeError imported
            # from google.net.proto would only work when run on the develop
            # server. This work around code was found here:
            # https://github.com/googlecloudplatform/datastore-ndb-python/issues/143
            if e.__class__.__name__ == 'ProtocolBufferDecodeError':
                raise endpoints.BadRequestException(
                    'Bad or corrupt %s websafe key: %s' %
                    (entity_kind, websafe_key)
                )
            else:
                raise

        if not entity:
            raise endpoints.NotFoundException(
                'No %s found with websafe key: %s' % (entity_kind, websafe_key)
            )

        return entity


# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference, checking it exists first
        conf = self._checkEntityExists(request.websafeConferenceKey, 'conference')

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = self._checkEntityExists(request.websafeConferenceKey, 'conference')

        # Get profile of creator in order to return their name
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = self._checkEntityExists(wsck, 'conference')

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground', http_method='GET',
                      name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city == "London")
        q = q.filter(Conference.topics == "Medical Innovations")
        q = q.filter(Conference.month == 6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )


# - - - Sessions - - - - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        session_form = SessionForm()

        for field in session_form.all_fields():
            if hasattr(session, field.name):
                # Convert date and time to stings
                if field.name == "date" or field.name == "startTime":
                    setattr(session_form, field.name,
                            str(getattr(session, field.name)))
                else:
                    setattr(session_form, field.name,
                            getattr(session, field.name))
            elif field.name == "confWebsafeKey":
                setattr(session_form, field.name,
                        session.key.parent().urlsafe())
            elif field.name == "websafeKey":
                setattr(session_form, field.name, session.key.urlsafe())

        session_form.check_initialized()
        return session_form


    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # Check to see if there is a user logged in. If so, get their id.
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # Check required properties are present.
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")
        if not request.typeOfSession:
            raise endpoints.BadRequestException(
                "Session 'typeOfSession' field required")
        if not request.confWebsafeKey:
            raise endpoints.BadRequestException(
                "Session 'confWebsafeKey' field required")

        # Check to see if the logged in user created the conference that this
        # session is being added to.
        conf = self._checkEntityExists(request.confWebsafeKey, 'conference')

        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the conference owner can add a session to a conference.')

        # Copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # Don't need to store the conference websafe key in the session object.
        del data['confWebsafeKey']
        del data['websafeKey']

        # Convert date and start time from strings to Date and Time objects.
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10],
                                             "%Y-%m-%d").date()

        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'],
                                                  "%H:%M").time()

        # Generate session id and key
        c_key = conf.key
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key

        # Create the session object and put it in the database
        Session(**data).put()

        # Check if the princple speaker of this session is speaking at more
        # than one session at this conference
        wspsk = data['speakerWebSafeKeys'][0]
        qry = Session.query(ancestor=conf.key)
        qry = qry.filter(Session.speakerWebSafeKeys == wspsk)

        if qry.count() > 1:
            # Get name of speaker and sessions
            speaker_key = ndb.Key(urlsafe=wspsk)
            speaker = speaker_key.get()

            sessions = qry.fetch(projection=[Session.name])
            session_names = ', '.join(session.name for session in sessions)

            # Queue a task to put it in the memcache
            taskqueue.add(params={'speakerName': speaker.name,
                                  'sessionNames': session_names},
                          url='/tasks/set_featured_speaker')

        return request


    @endpoints.method(SessionForm, SessionForm, path='session',
                      http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)


    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
                      path='conference/{websafeConferenceKey}/sessions',
                      http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return all the sessions for a particular conference."""
        # Check if a conference exists given websafeConferenceKey
        conf = self._checkEntityExists(request.websafeConferenceKey,
                                       'conference')

        # Query for all sessions that have conf as an ancestor.
        qry = Session.query(ancestor=conf.key)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in qry]
        )


    @endpoints.method(
        SESSION_BY_TYPE_GET_REQUEST, SessionForms,
        path='conference/{websafeConferenceKey}/sessions/{typeOfSession}',
        http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Return sessions for a particular conference of a specified type."""
        # Check if a conference exists given websafeConferenceKey
        conf = self._checkEntityExists(request.websafeConferenceKey,
                                       'conference')

        # Query for all sessions that have conf as an ancestor and of
        # type 'typeOfSession'
        qry = Session.query(ancestor=conf.key)
        qry = qry.filter(Session.typeOfSession == request.typeOfSession)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in qry]
        )


    @endpoints.method(SESSION_BY_SPEAKER_GET_REQUEST, SessionForms,
                      path='speaker/{websafeSpeakerKey}/sessions',
                      http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Returns all sessions across all conferences by speaker."""
        # Check if a speaker exists given the websafeSpeakerKey
        wsspk = request.websafeSpeakerKey
        self._checkEntityExists(wsspk, 'speaker')

        # Filter sessions by speaker
        qry = Session.query()
        qry = qry.filter(Session.speakerWebSafeKeys == wsspk)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in qry]
        )


    @endpoints.method(
        SessionQueryDurationForm, SessionForms, path='getSessionsByDuration',
        http_method='GET', name='getSessionsByDuration'
    )
    def getSessionsByDuration(self, request):
        """Get sessions of a duration between the specified min and max.

        Can also just specify a min or max duration.
        """
        # If no minDuration specified, assume a value of zero
        if not request.minDuration:
            request.minDuration = 0

        # Session needs to be sorted first on the duration property
        qry = Session.query().order(Session.duration)
        qry = qry.filter(Session.duration >= request.minDuration)

        # Only apply the max duration filter if the maxDuration parameter
        # is present
        if request.maxDuration:
            qry = qry.filter(Session.duration <= request.maxDuration)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in qry]
        )


    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='getNonWorkshopSessionsBefore7',
                      http_method='GET', name='getNonWorkshopSessionsBefore7')
    def getNonWorkshopSessionsBefore7(self, request):
        """Get sessions that are not of type 'Workshop' and are before 7 pm."""
        # Do a query for non-workshops and get a list of keys.
        qry_nonworkshops = Session.query(Session.typeOfSession != 'Workshop')
        qry_nonworkshops_keys = []
        for key in qry_nonworkshops.iter(keys_only=True):
            qry_nonworkshops_keys.append(key)

        # Do a query for sessions before 7 pm
        qry_before_7 = Session.query(
            Session.startTime < datetime.strptime("19:00", "%H:%M").time()
        )
        qry_before_7_keys = []
        for key in qry_before_7.iter(keys_only=True):
            qry_before_7_keys.append(key)

        # Find the keys that are common between the two sets of keys
        keys_nonworkshop_before_7 = list(set(qry_nonworkshops_keys) &
                                         set(qry_before_7_keys))

        # Get the session entities that are not workshops and before 7 pm
        sessions = ndb.get_multi(keys_nonworkshop_before_7)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )


# - - - Speakers - - - - - - - - - - - - - - - - - - - -

    def _copySpeakerToForm(self, speaker):
        """Copy relevant fields from Speaker to SpeakerForm."""
        spf = SpeakerForm()

        for field in spf.all_fields():
            if hasattr(speaker, field.name):
                setattr(spf, field.name, getattr(speaker, field.name))
            elif field.name == "websafeKey":
                setattr(spf, field.name, speaker.key.urlsafe())

        spf.check_initialized()
        return spf


    def _createSpeakerObject(self, request):
        """Create Speaker object, returning SpeakerForm/request."""
        # Need to be logged in to create a speaker entity
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # Speaker name is a required property
        if not request.name:
            raise endpoints.BadRequestException("Speaker 'name' field required")

        # Copy SpeakerForm/ProtoRPC Message into dictionary
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']

        # Make the logged in user the parent of the Speaker object.
        p_key = ndb.Key(Profile, user_id)
        s_id = Speaker.allocate_ids(size=1, parent=p_key)[0]
        s_key = ndb.Key(Speaker, s_id, parent=p_key)
        data['key'] = s_key

        # Create the Speaker entity in the datastore
        Speaker(**data).put()

        return request


    @endpoints.method(SpeakerForm, SpeakerForm, path='speaker',
                      http_method='POST', name='createSpeaker')
    def createSpeaker(self, request):
        """Create new speaker."""
        return self._createSpeakerObject(request)


    @endpoints.method(message_types.VoidMessage, SpeakerForms, path='speakers',
                      http_method='GET', name='getSpeakers')
    def getSpeakers(self, request):
        """Return currently defined speakers.

        Useful for the front end session form to show a choice of speakers.
        """
        speakers = Speaker.query()

        return SpeakerForms(
            items=[self._copySpeakerToForm(speaker) for speaker in speakers]
        )


    @endpoints.method(SpeakerQueryOrganizationForm, SpeakerForms,
                      path='getSpeakersByOrganization', http_method='GET',
                      name='getSpeakersByOrganization')
    def getSpeakersByOrganization(self, request):
        """Return all the speakers belonging to a specified organization."""
        qry = Speaker.query(Speaker.organization == request.organization)

        return SpeakerForms(
            items=[self._copySpeakerToForm(speaker) for speaker in qry]
        )


# - - - Wishlist - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional()
    def _updateWishlist(self, request, add=True):
        """Add or remove a session from a user's wishlist."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # Check if the session specified in the request exists.
        wssk = request.websafeSessionKey
        self._checkEntityExists(wssk, 'session')

        if add:
            # Check if user already has this session in their wishlist
            if wssk in prof.sessionKeysInWishlist:
                raise ConflictException(
                    "You already have this session in your wishlist"
                )

            # Update the user's wishlist
            prof.sessionKeysInWishlist.append(wssk)
            retval = True

        # Remove session from wishlist
        else:
            # Check if session is in wishlist
            if wssk in prof.sessionKeysInWishlist:
                prof.sessionKeysInWishlist.remove(wssk)
                retval = True
            else:
                retval = False

        # Write the updated profile to the datastore
        prof.put()
        return BooleanMessage(data=retval)


    @endpoints.method(UPDATE_WISHLIST_REQUEST, BooleanMessage,
                      path='session/{websafeSessionKey}/wishlist',
                      http_method='PUT', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add session to logged in user's wishlist."""
        return self._updateWishlist(request)


    @endpoints.method(UPDATE_WISHLIST_REQUEST, BooleanMessage,
                      path='session/{websafeSessionKey}/wishlist',
                      http_method='DELETE', name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        """Remove session from the logged in user's wishlist."""
        return self._updateWishlist(request, add=False)


    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='sessions/wishlist', http_method='GET',
                      name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Get list of sessions that the user has in their wishlist."""
        # Get user profile
        prof = self._getProfileFromUser()

        # Get session keys from user's wishlist and the session objects
        session_keys = (
            [ndb.Key(urlsafe=wssk) for wssk in prof.sessionKeysInWishlist]
        )
        sessions = ndb.get_multi(session_keys)

        # Return sessions
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )


# - - - Featured Speaker - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheFeaturedSpeaker(request):
        """Create Featured Speaker and assign to memcache."""
        featured_speaker = FEATURED_SPEAKER_TPL % (request.get('speakerName'),
                                                   request.get('sessionNames'))
        memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, featured_speaker)

        return featured_speaker


    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='getFeaturedSpeaker', http_method='GET',
                      name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return Featured Speaker from memcache."""
        return StringMessage(
            data=memcache.get(MEMCACHE_FEATURED_SPEAKER_KEY) or "")


api = endpoints.api_server([ConferenceApi]) # register API
