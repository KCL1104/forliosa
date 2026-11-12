# Forliosa's private SearXNG for the news worker (apps/api forliosa.news.searxng). See docs/deploy.md §2.6.
#
# The official image, pinned to a released tag (published 2026-10-28; at least two weeks old when it was pinned)
# and to that tag's multi-architecture digest, so a rebuild never picks up a different release.
# To upgrade: choose a tag from https://hub.docker.com/r/searxng/searxng/tags that is at least two weeks old, update
# the tag and the digest together, read that release's searx/settings.yml for renamed keys, then run
#   cd apps/api && uv run python -m forliosa.news searxng-check "台積電"
FROM docker.io/searxng/searxng:2026.10.28-c360868e5@sha256:268a4b460136dcefc8f2e896b6098ba3f770c8218dbbddcb86811b06b06816f1

# Our settings: news engines only, JSON output, private (no limiter, no image proxy). The secret key is never in
# this file or the image: SEARXNG_SECRET is set on the service at run time.
COPY settings.yml /etc/searxng/settings.yml
ENV SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml

# The base image listens on [::]:8080 (GRANIAN_HOST / GRANIAN_PORT): IPv6 and IPv4, as Railway's private network
# needs. Do not publish this port to the internet.
EXPOSE 8080
