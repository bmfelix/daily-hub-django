# Daily Hub · Django

A personal dashboard. Each menu link is one module, and each module is one class that calls its own API or database table.

This is one of three builds of the same app (Django, Next.js, Laravel), so the frameworks can be compared side by side.

## Modules

| Page     | Class            | Data source                                   |
|----------|------------------|-----------------------------------------------|
| Weather  | `WeatherModule`  | [Open-Meteo](https://open-meteo.com) (no key) |
| News     | `NewsModule`     | [Hacker News search API](https://hn.algolia.com/api) (no key) |
| To-do    | `TodoModule`     | Postgres (`Task` model)                       |
| Concerts | `ConcertsModule` | [Ticketmaster Discovery API](https://developer.ticketmaster.com) (free key) |
| Notes    | `NotesModule`    | Postgres (`Note` model)                       |
| Radio    | `RadioModule`    | [iHeartRadio](https://www.iheart.com) song history (WEBN) and [Triton Digital](https://www.tritondigital.com) now-playing feed (WKRQ), no keys |

Modules can also give the homepage a live card instead of their summary. The Radio card shows the song playing now on each station. WEBN's newest song can appear about a minute after it starts, so its card may briefly say "Last played".

## How it is built

- `hub/modules/base.py` defines `HubModule`, a class-based view. Each module subclasses it and returns its page data from `load()`.
- API modules keep their HTTP calls in a small client class (for example `OpenMeteoClient`). Tests swap that class for a fake, so they run without the internet.
- `hub/modules/__init__.py` holds the `MODULES` list. The menu, the homepage cards, and the URLs are all built from this list. To add a page, write a module class and a template, then add the class to the list.
- The menu collapses into a "Menu" button below 640px wide.

## Live updates

The Radio card on the homepage updates without a reload:

1. The **listener** container (`python manage.py listen_radio`) asks both stations for their song every 15 seconds. The feeds cannot be subscribed to, so it polls.
2. When a song changes (or the current song ends), it renders the card and sends it to the `radio` group through **Django Channels**, with **Redis** carrying the message between containers.
3. Each open homepage holds a WebSocket to `/ws/radio/` (`hub/consumers.py`), receives the new card, and swaps it in (`hub/static/hub/live.js`).

The web container runs **Uvicorn** (an ASGI server) so it can serve both pages and WebSockets.

## Artist pages

Click an artist on the homepage card or the Radio page to see everything MusicBrainz has on them: photo, origin, active years, rating, genres, members (with roles and years), the full discography with cover art, links (listen, official, social, concerts, buy, reference), aliases, related artists, and identifiers.

- **Fetched once, then saved.** `hub/musicbrainz.py` looks the artist up the first time and stores the full record in Postgres (`Artist`), plus which radio name matched it (`ArtistName`, which also remembers names with no match). Saved artists are refreshed after 30 days; unmatched names are retried after 7.
- **Fetched ahead of time.** The listener looks up each artist as their song comes on, so most clicks open instantly. If a lookup is still needed, the page shows a "please wait" overlay.
- **Polite to MusicBrainz.** Every request names the app and a contact address, requests are at least 1.1 seconds apart, and a "slow down" reply (503) is retried once.
- **Careful matching.** A result must match the name (or an alias), not just look similar. For "A [+] B" or "A, B & C", the full name is tried first, then the first artist.
- **Name matching.** Searches cover both main names and aliases, so "Matchbox 20" finds Matchbox Twenty.
- **Wikipedia.** Each artist's opening text comes from their English Wikipedia page, found through MusicBrainz's links and then by name. The text is CC BY-SA, so pages credit and link it. Run `python manage.py update_artists` once to fill in artists saved before this existed.
- Photos come from Wikimedia Commons. Covers come from the Cover Art Archive, then Apple. Wikipedia's album covers are non-free, so they are not used.

## Song previews

The listener looks up each song the stations play, three per check to stay within Apple's limit of about 20 requests a minute. Results are saved in `Song`, refreshed after 30 days, and retried after 7 if nothing was found.

Apple's 30-second preview comes first, then Deezer's. Deezer's addresses expire within minutes, so only the track ID is saved and `/songs/<id>/preview/` fetches a fresh address when someone presses play. Google Play Music closed in 2020 and YouTube Music has no preview API, so YouTube Music is a search link. Spotify stopped giving new apps previews in 2024, so Spotify is a search link too.

Each station's live audio plays from the homepage card and the Radio page. It comes directly from iHeart (WEBN) and Triton (WKRQ) and includes the stations' ads.

## Spotify

The top homepage card shows a playlist player and what you are playing or last played. Both are optional.

- **Playlist:** set `SPOTIFY_PLAYLIST_URL` in `.env` to a public playlist's share link, or several separated by commas. It needs no account. Visitors logged in to Spotify may hear full songs; everyone else gets short previews.
- **Listening:** this needs Spotify Premium, because Spotify requires it of the owner of a developer app.
  1. Create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) using the Web API, with the redirect URI `http://127.0.0.1:8001/spotify/callback/`. Spotify does not accept `localhost` here.
  2. Put its client ID and secret in `.env` as `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`, then run `docker compose up -d`.
  3. Log in to the site and click **Connect Spotify** on the homepage.

The login renews itself. To disconnect, delete the Spotify account entry in the admin. Anyone who opens the site can see what you are playing.

## Other pages

- **Charts** counts every play the listener hears, per station and per week, in the `Play` model.
- **Concerts** lists Cincinnati, Dayton, and Columbus shows. Set `TICKETMASTER_API_KEY` in `.env`.
- **Agenda** is private to the logged-in owner. Make an Apple calendar public, copy its address from Get Info, and put it in `CALENDAR_URLS` in `.env`. Separate several with commas. Anyone with one of those links can read that calendar, so keep them private.
- **Listening** shows top Spotify artists and tracks once Spotify is connected.
- **About** comes from `Profile` and `Project` in the admin, plus recent public GitHub work (`GITHUB_USERNAME`).
- **How it's built** compares the three builds and is linked from the footer.

## Going public

Before the site leaves your private network, set these in `.env`: `DJANGO_DEBUG=0`, a long random `DJANGO_SECRET_KEY`, and `DJANGO_SECURE_COOKIES=1`, which also means logging in only through an HTTPS address. Add the public address to `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.

Five wrong passwords lock a username for an hour. To unlock sooner: `docker compose exec web python manage.py axes_reset`.

## Admin

Log in from the menu to change things. Visitors can read every page, but only logged-in staff can change to-dos and notes.

Set `DJANGO_REQUIRE_LOGIN=0` in `.env` to open to-dos, notes, and the agenda to anyone who can reach the site. The admin always needs a login.

Create your login once: `docker compose exec web python manage.py createsuperuser`.

`/admin/` has full create, edit, and delete for tasks, notes, artists, radio names, and songs:

- **Artists:** add one from just a MusicBrainz ID. Tick "keep my edits" so the 30-day refresh leaves your changes alone. A deleted artist comes back if the radio plays them again.
- **Radio names:** filter for empty artists to see names with no match, and pick the right artist to fix one.
- **Songs:** tick "keep my edits" the same way, or use the "Look up previews again" action.

## Run with Docker

1. `cp .env.example .env` and set a secret key and database password.
2. `docker compose up -d --build`
3. Open http://localhost:8001

Stop it with `docker compose down`.

## Tests

```sh
docker compose exec web python manage.py test
```

## Stack

Django 6.1 · Django Channels 4.3 · Python 3.13 · Postgres 17 · Redis 8 · Uvicorn · WhiteNoise · Docker Compose
