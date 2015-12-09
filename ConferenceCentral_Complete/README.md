App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's
   running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.

## Session and Speaker class design
### Sessions
A conference can have one or more sessions. A session entity is a child of
a conference as it is an unique event in the world. Only the conference
organizer can create a session of a conference. The session name and type are
required attributes of the Session class, while other attributes defined in the
[project specification][7] are optional. The `speaker` attribute in the spec has
been replaced by `speakerWebSafeKeys` to hold the websafe keys of one or more
speaker entities (see below).

The SessionForm class defines the Google Protocol Remote Procedure Call (RPC)
message to and from the front end. It has the extra field `confWebSafeKey` in order
for the session to be attached to the specified Conference object. This is a required
field when creating a session.

### Speaker entity
Each speaker has been implemented as its own entity. This allows the storing of
extra information such as speaker organization, email, website, which wouldn't make sense
to be stored in the Session class. A speaker could speak at more that one session,
so it would not make sense to make Speaker a child of Session in the Datastore.
Instead Speaker is a child of Profile, so only logged in users can create a speaker
(for data accountability) and affords that only the speaker creator could edit a
speaker.

To support speaker as its own entity, `createSpeaker` and `getSpeakers` endpoint
methods have been implemented. `getSpeakers` would be useful for the front end
session creation form to call to provide options for the speaker field. If the
correct speaker is not in the list, the user could then be given the opportunity
to create a speaker.

The SpeakerForm RPC message class as the extra field `websafeKey` so that the
front end may reference a speaker entity when creating a session.

## Additional Queries
### Get session by duration
Let's say you don't like sessions that are too long. You might want to list all
the sessions that are less than an hour. Or you want to go in-depth on a topic
and want a list of sessions over an hour. The `getSessionByDuration` query does
this by accepting two parameters, `minDuration` and `maxDuration`. Users may specify
either of these parameters or both to form a query. Durations are
measured in minutes.

### Get speaker by organization
If you are interesting in speakers from your favourite company or organization, you
can use the `getSpeakerByOranisation` query to list them.

## Query related problem
### The Problem
Udacity asked about the following query. What if you don't like sessions that are workshops
and don't like sessions after 7 pm. The problem here is that there are two inequality filters
on two different properties. One of the restricts of Datastore is that an inequality filter
can only be applied to at most one property in a query to the Datastore.

### A solution
One solution would be to split the problem into two queries, one for the session type
and one for the start time. This will produce two lists of keys, which can be turned
into [Phython sets][8] as keys are unique. We can then get the intersection of these
to sets with `intersection` method or the equivalent `&` operator. The result will
be sessions that are not workshops and before 7 pm. This solution has been implemented
in the method `conference.getNonWorkshopSessionsBefore7`.

[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
[7]: https://docs.google.com/document/d/1H9anIDV4QCPttiQEwpGe6MnMBx92XCOlz0B4ciD7lOs/pub
[8]: https://docs.python.org/2/library/sets.html
