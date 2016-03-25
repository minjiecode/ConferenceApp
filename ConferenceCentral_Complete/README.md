# Conference Organization App

## Description

This is a python based project htat utilizes Google App Engine to create APIs that are accessible from a web-based conference organization app. 

The web app can be accessed [here](https://udacity-conference-108.appspot.com/). The APIs for the app can be accesssed through the [API exploreer](https://udacity-conference-108.appspot.com/_ah/api/explorer)

> \**This is a project for the Udacity Nanodegree Course*

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions

1. Create an application in Google Developer Console
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Create client ID in API Manager.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4]. 
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.
1. To access APIs, visit: https://{your-app-id}.appspot.com/_ah/explorer

## Design Choices
#### Task1. Add Session to a Conference
To support the ability to add sessions to conferences, the following endpoints were created:
* getConferenceSessions(websafeConferenceKey) -- Given a conference, return all sessions
* getConferenceSessionsByType(websafeConferenceKey, typeOfSession) Given a conference,return all sessions of a specified type (eg lecture, keynote, workshop)
* getSessionsBySpeaker(speaker) -- Given a speaker, return all sessions given by this particular speaker, across all conferences
* createSession(SessionForm, websafeConferenceKey) -- open to the organizer of the conference

I used string property for session name, highlights, speaker, the type Of session and conference, which allows for unicode string values. And I used the integer property for the duration tof the session. And I used the date property and time property for date and time respectively. The speaker name is required for each session. 

And the SessionForm class is modeled based on the session class with date/time attribute converted to string and this is used for the outbound form message. 


#### Task2. Add Sessions to User Wishlist
Users should be able to mark some sessions that they are interested in and retrieve their own current wishlist.
To achieve it, I created the following endpoints and remodeled the profile class to included sessionKeysInWishlist with string property.
* addSessionToWishlist(SessionKey) -- adds the session to the user's list of sessions they are interested in attendingYou can decide if they can only add conference they have registered to attend or if the wishlist is open to all conferences.
* getSessionsInWishlist() -- query for all the sessions in a conference that the user is interested in
* deleteSessionInWishlist(SessionKey) -- removes the session from the user’s list of sessions they are interested in attending


#### Task 3. Work on indexes and queries
Come up with 2 additional queries:
* getAttendeesByConference(websafeonferenceKey) -- Given a specified conference, return all attendees for the conference. (ProfileForms is added to the models.py)
* getSessionsByHighlights(highlight) -- Given a specified highlight, return all sessions with this specific highlight, across all conferences.
Solve the following query related problem
Let’s say that you don't like workshops and you don't like sessions after 7 pm. How would you handle a query for all non-workshop sessions before 7 pm? What is the problem for implementing this query? What ways to solve it did you think of?
To query all non-workshop sessions before 7 pm we need to two in-equality filters. As Google datastore API does not support two in-equality filters we cannot do that in only one query. However, we can seperate them into two queries to solve it. 

#### Task 4. Add a task
When a new session is added to a conference, check the speaker. If there is more than one session by this speaker at this conference, also add a new Memcache entry that features the speaker and session names. You can choose the Memcache key.
To implemented this logic, I creacted a task queue in the _createSessionObject function in conference.py. And corresponding handler `CheckFeaturedSpeakerHandler` in the main.py. When a new session is created, a task queue with speaker name and websafeConferenceKey as parameters is created. And the handler then 
queries for all sessions in the same conference of the newly created session, looking for other sessions with the speaker's name. If another session with the same speaker is found, the speaker become the new featured speaker and is added to memecache.   
And I also implemented `getFeaturedSpeaker()` endpoint method to give access to the featured speaker's name and sessions he/she will be speaking at. 


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
