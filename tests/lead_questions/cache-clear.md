HANDOFF
DID:
- Planned the 5-minute browser cache for the items list as 12 testable behaviours plus 5 open points. No spec line covers caching, so there is no CONFLICT.
QUESTION: Should createItem or moveItem on the same client clear the cached items list (frontend/src/api.js:32, frontend/src/api.js:35), or may a just-created item stay missing from the list for up to 5 minutes?
RECOMMEND: Clear the cached listItems entries on a successful createItem or moveItem. Otherwise the user creates an item and does not see it, which reads as a bug.
SIZE: a few lines in frontend/src/api.js, plus one test per method.
END HANDOFF
