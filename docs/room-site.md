# The room as a static site

How the room pages ship without the room server serving them, for the
PyLadies Remote move off kai-server (teable:coilyco/deploy#8452).

## Same-origin

One CloudFront distribution at the room's host serves the pages from S3 and
forwards `/api/*` to the room server, uncached, with POST bodies and the
control-token header passed through. The pages already call the API relative
(`api/room`, `api/room/events`), so they need no API origin and no CORS, and
the event stream stays same-origin. The server's 15s SSE heartbeat sits under
CloudFront's 30s origin read timeout.

This depends on the server reading the viewer's address correctly behind the
proxy, because the room rate-limits per address. That fix is on the server.

## The export

`just room-site [out]` writes `dist/room-site` by default:

- `index.html`, `screen/index.html` and `present/index.html`. The project-sites
  viewer function rewrites an extensionless path to its directory index, so
  `/screen` serves without the URL changing.
- `room.css`, `room.js`, `views.js`, and `creatures/*.png`, the subjects' logos.
- `404.html`, which the distribution maps misses to.

Every page gets `<base href="/">`, so relative URLs resolve from the root and
`/screen/` with a trailing slash works like `/screen`. The pages hold no
fragment links, which a base would redirect. `housecast/tests/test_room_site.py`
holds the layout, the base and the no-absolute-API rule.

## Publishing

The bucket, certificate and DNS live in coilyco/infrastructure's
`terraform/aws-project-sites` and are the sysadmin seat's to apply. Syncing the
export into the bucket uses the shared `project-sites-publish` user, the same
way sirens-echo's `publish-site.sh` does.
