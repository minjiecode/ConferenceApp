#!/usr/bin/env python

"""
main.py -- Udacity conference server-side Python App Engine
    HTTP controller handlers for memcache & task queue access

$Id$

created by wesc on 2014 may 24

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

import webapp2
from google.appengine.api import app_identity
from google.appengine.api import mail
from conference import ConferenceApi

class SetAnnouncementHandler(webapp2.RequestHandler):
    def get(self):
        """Set Announcement in Memcache."""
        ConferenceApi._cacheAnnouncement()
        self.response.set_status(204)


class SendConfirmationEmailHandler(webapp2.RequestHandler):
    def post(self):
        """Send email confirming Conference creation."""
        mail.send_mail(
            'noreply@%s.appspotmail.com' % (
                app_identity.get_application_id()),     # from
            self.request.get('email'),                  # to
            'You created a new Conference!',            # subj
            'Hi, you have created a following '         # body
            'conference:\r\n\r\n%s' % self.request.get(
                'conferenceInfo')
        )

# Task 4
class CheckFeaturedSpeakerHandler(webapp2.RequestHandler):

    def post(self):
        """Add speaker as featured speaker to memecache if :
            pass speaker is already speaking at conference."""
        # get speaker from newly created session
        speaker = self.request.get('speaker')
        session_list = []
        # get websafeConferenceKey and then get conference object
        wsck = self.request.get('websafeConferenceKey')
        conf = ndb.Key(urlsafe=wsck).get()
        # get all sessions for conference
        conference_sessions = Session.query(ancestor=conf.key)
        # store all instances of speaker speaking at conference
        for session in conference_sessions:
            if session.speaker == speaker:
                session_list.append(str(session.name))
        # if speaker is speaking more than once, add to memcache
        if len(session_list) > 1:
            # create unique memcache key for conference (using conf key):
            memcache_key = MEMCACHE_FEATURED_SPEAKER_KEY + str(wsck)
            # create string of all sessions by speaker
            session_string = ', '.join(session_list)
            # set memcache on datastore using key, speaker, and output:
            memcache.set(memcache_key, "Featured speaker is: {}. Sessions include: {}"
                                       "".format(speaker,
                                                 session_string))

app = webapp2.WSGIApplication([
    ('/crons/set_announcement', SetAnnouncementHandler),
    ('/tasks/send_confirmation_email', SendConfirmationEmailHandler),
    ('/tasks/check_featured_speaker'), CheckFeaturedSpeakerHandler)
], debug=True)
