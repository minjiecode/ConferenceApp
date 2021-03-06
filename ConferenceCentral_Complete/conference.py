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
from models import ProfileForms
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import SessionForm
from models import SessionForms
from models import Session


from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
EMCACHE_FEATURED_SPEAKER_KEY = "FEATURED_SPEAKER"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
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

SESS_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)

SESS_GET_REQUEST_BY_TYPE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    typeOfSession = messages.StringField(1),
    websafeConferenceKey = messages.StringField(2),
)

SESS_GET_BY_SPEAKER_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

SESS_GET_BY_HIGHLIGHTS_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    highlights=messages.StringField(1),

)

SESS_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey = messages.StringField(1),
)


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

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

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

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
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
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


# - - - Session Object - - - - - - - - - - - - - - - - - - - 
    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                if field.name.endswith('date') or field.name.endswith('startTime'):
                    setattr(sf,field.name,
                            str(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session,field.name))
            elif field.name == "sessionSafeKey":
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf


    def _createSessionObject(self,request):
        """Create Session Object, returning SessionForm/request"""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        if not request.name:
            raise endpoints.BadRequestException(
                "Session 'name' field required")
        #Get conference key
        wsck = request.websafeConferenceKey
        #Get conference object
        c_key = ndb.Key(urlsafe = wsck)
        conf = c_key.get()
        #check if conf exist
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)
        #check if user is the creator of the conference
        if conf.organizerUserId != getUserId(endpoints.get_current_user()):
            raise endpoints.ForbiddenException(
                'You must be the organizer to create a session.')

        #copy Session/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_field()}
        #convert date and time from strings to Date objects;
        if data['date']:
            data['date'] = datetime.strptime(
                data['data'][:10], "%Y-%m-%d".date())
        if data['startTime']:
            datat['startTime'] = datetime.strptime(
                data['startTime'][:10], "%H,%M").time()
        # Allocate new Session ID with Conference key as the parent
        session_id = Session.allocate_ids(size = 1, parent = c_key)[0]
        # Make Session key from ID
        session_key = ndb.Key(Session, session_id, parent = c_key)
        data['key'] = session_key
        #Save session into database
        Session(**data).put()
        # Taskque for featuredSpeaker endpoint
        #check for featured speaker in conference:
        taskqueue.add(params={'speaker': data['speaker'],
                              'websafeConferenceKey': wsck
                              },
                      url='/tasks/check_featured_speaker')

        session = session_key.get()
        return self._copySessionToForm(session)



    #createSession(SessionForm, websafeConferenceKey) -- open only to the organizer of the conference
    @endpoints.method(SESS_POST_REQUEST, SessionForm,
        path = 'conference/{websafeConferenceKey}/newSession',
        http_method = 'POST', name = 'createSession')
    def createSession(self, request):
        """Create New Session (websafeConferenceKey)"""
        return self._createSessionObject(request)



    #getConferenceSessions(websafeConferenceKey) -- Given a conference, return all sessions
    @endpoints.method(CONF_GET_REQUEST, SessionForms, 
        path='conference/session/{websafeConferenceKey}',
        http_method='GET', name = 'getConferenceSessions')
    def getConferenceSessions(self, request):
        """ Given a conference, return all sessions"""
        wsck = request.websafeConferenceKey
        if not wsck:
            raise endpoints.NotFoundException(
                'Conference key required')
        #check if conference exist
        try:
            conf = ndb.Key(urlsafe = wsck).get()
        except:
            raise endpoints.NotFoundException(
                'No conference found with key:%s' % wsck)
        #check if there are session in the conference
        sesss = Session.query(ancestor=conf.key)

        return SessionForms(
            items = [self._copySessionToForm(sess) for sess in sesss])


    
    @endpoints.method(SESS_GET_REQUEST_BY_TYPE, SessionForms,
        path='conference/{websafeConferenceKey}/sessions/{typeOfSession}',
        http_method ='GET', name = 'getConferenceSessionsByType')
    def getConferenceSessionsByTpe(self, request):
        """Given a conference, return all sessions of a specified type (eg lecture, keynote, workshop)"""
        #get the conference key
        wsck = request.websafeConferenceKey
        #get the type of session we want
        typeOfSess = request.typeOfSession
        if not wsck:
            raise endpoints.NotFoundException(
                'Conference key required')
        try:
            conf = ndb.Key(urlsafe = request.wsck).get()
        except:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' %wsck)
        #
        sesss = Session.query(ancestor = conf.key)

        sesss = sesss.filter(Session.typeOfSession == typeOfSess)
        
        return SessionForms(items = [self._copySessionToForm(sess) for sess in sesss])

    #getSessionsBySpeaker(speaker) -- Given a speaker, return all sessions given by this particular speaker, across all conferences
    @endpoints.method(SESS_GET_BY_SPEAKER_REQUEST, SessionForms,
        path='conference/session/{speaker}',
        http_method ='GET', name = 'getConferenceSessionsByType')
    def getConferenceSessionsByTpe(self, request):
        """Given a speaker, return all sessions given by this particular speaker, across all conferences"""
        speaker = request.speaker
        if not speaker:
            raise endpoints.NotFoundException(
                'Speaker name required')
        sesss = Session.query(Session.speaker == request_speaker)
        return SessionForms (
            items = [self._copySessionToForm(sess) for sess in sesss])


    #Task 3. Additional function: Get session by highlight.
    @endpoints.method(SESS_GET_BY_HIGHLIGHTS_REQUEST, SessionForms,
                      path='/sessions/highlights/{highlights}',
                      http_method='GET', name='getSessionsByHighlights')
    def getSessionsByHighlights(self, request):
        """Given a specified highlight, return all sessions with this specific highlight, across all conferences."""
        sessions = Session.query()
        sessions = sessions.filter(Session.highlights == request.highlights)
        # return set of SessionForm objects
        return SessionForms(items=[self._copySessionToForm(session) for session in sessions])

    #Task 4. Addtional function: Get attendees by session.
    @endpoints.method(CONF_GET_REQUEST, ProfileForms,
            path = '/getAttendeeByConference/{websafeConferenceKey',
            http_method = 'GET', name = 'getAttendeeByConference')
    def getAttendeesByConference(self, request):
        """Given a specified conference, return all attendees for the conference."""
        wsck = request.websafeConferenceKey
        profile = Profile.query()
        attendees = []
        for pro in profiles:
            if wsck in pro.conferenceKeysToAttend:
                attendees.append(pro)
        # return set of profileform objects
        return ProfileForms(items = [self.copyProfileToForm(attendee) for attendee in attendees])
    
    
    @endpoints.method(SESS_GET_REQUEST, SessionForm,
                      path="addSessionToWishlist",
                      http_method="POST", name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add the session to the user's list of sessions they are interested in attending"""
        # Get the session key
        sessionKey = request.sessionKey
        # Get the session object
        session = ndb.Key(urlsafe=sessionKey).get()
        # Check that session exists or not
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % sessionKey)

        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        profile = self._getProfileFromUser()
        if not profile:
            raise endpoints.BadRequestException(
                'Profile does not exist for user')
        # Check if key and Session match
        if not type(ndb.Key(urlsafe=sessionKey).get()) == Session:
            raise endpoints.NotFoundException(
                'This key is not a Session instance')
        # Add the session to wishlist
        if sessionKey not in profile.sessionKeysInWishlist:
            try:
                profile.sessionKeysInWishlist.append(sessionKey)
                profile.put()
            except Exception:
                raise endpoints.InternalServerErrorException(
                    'Error in storing the wishlist')
        return self._copySessionToForm(session)


        @endpoints.method(message_types.VoidMessage, SessionForms,
                            path = "getSessionsInWishlist", 
                            http_method = "GET", name = 'getSessionsInWishlist')
        def getSessionsInWishlist(self, request):
            """Query for all the sessions in a conference that the user is interested in"""
            # Get Profile
            profile = self._getProfileFromUser()
            if not profile:
                raise endpoints.BadRequestException(
                    'Profile does not exist for user')
                # Get all of the session keys in database
                sessionkeys = [ndb.Key(urlsafe = sessionkey) 
                                for sessionkey in profile.sessionKeysInWishlist]
                sessions = ndb.get_multi(sessionkeys)
                # Return set of SessionForm objects per conference
                return SessionForms(items = [self._copySessionToForm(session)
                                             for session in sessions])

        @endpoints.method(SESS_GET_REQUEST, BooleanMessage,
                            path = "deleteSessionInWishlist/{sessionKey}",
                            http_method = "DELETE", name = 'deleteSessionInWishlist')
        def deleteSessionInWishlist(self, request):
            """removes the session from the user list of sessions they are interested in attending"""
            # Get the sessionKey
            sessionKey = request.sessionKey
            # Get the session object
            session = ndb.Key(urlsafe=sessionKey).get()
            if not session:
                raise endpoints.NotFoundException(
                    'No session found with key: %s' % sessionKey)
            user = endpoints.get_current_user()
            if not user:
                raise endpoints.UnauthorizedException('Authorization required')
            # Get profile
            profile = self._getProfileFromUser
            if not profile:
                raise endpoints.BadRequestException(
                    'Profile does not exist for user')
            # Check if key and Session match
            if not type(ndb.Key(urlsafe = sessionKey).get()) == Session:
                raise endpoints.NotFoundException(
                    'This key is not a Session instance')
            # Delete session from wishlist
            if sessionKey in profile.sessionKeysInWishlist:
                try:
                    profile.sessionKeysInWishlist.remove(sessionKey)
                    profile.put()
                except Exception:
                    raise endpoints.InternalServerErrorException(
                        'Error in storing the wishlist')
            return BooleanMessage(data=True)


# - - - Featured Speaker - - - - - - - - - - - - - - - - -
    @endpoints.method(CONF_GET_REQUEST, StringMessage,
                      path='featuredSpeaker',
                      http_method='GET',
                      name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Returns featured speaker and the sessions he's partaking in from
        memcache"""

        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # create memcache key based on conf key:
        memcache_key = MEMCACHE_FEATURED_SPEAKER_KEY + str(wsck)

        # try to find entry in memcache:
        output_ = memcache.get(memcache_key)
        if output_:
            return StringMessage(data=memcache.get(memcache_key))
        else:
            return StringMessage(
                data="There are no featured speakers for this conference.")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

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
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
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
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)




api = endpoints.api_server([ConferenceApi]) # register API
