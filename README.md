# Daily Hub · Django

A personal dashboard. Each menu link is one module, and each module is one class that calls its own API or database table.

This is one of three builds of the same app (Django, Next.js, Laravel), so the frameworks can be compared side by side.

## Modules

| Page     | Class            | Data source                                   |
|----------|------------------|-----------------------------------------------|
| Weather  | `WeatherModule`  | [Open-Meteo](https://open-meteo.com) (no key) |
| News     | `NewsModule`     | [Google News](https://news.google.com) top-stories RSS feed (no key; personal, non-commercial use only) |
| To-do    | `TodoModule`     | Postgres (`Task` model)                       |
| Concerts | `ConcertsModule` | [Ticketmaster Discovery API](https://developer.ticketmaster.com) (free key) |
| Notes    | `NotesModule`    | Postgres (`Note` model)                       |
| Radio    | `RadioModule`    | [iHeartRadio](https://www.iheart.com) song history (WEBN) and [Triton Digital](https://www.tritondigital.com) now-playing feed (WKRQ), no keys |
| Charts   | `ChartsModule`   | Postgres (`Play` model) |
| Agenda   | `AgendaModule`   | Google or Apple calendar links |
| Listening | `ListeningModule` | [Spotify Web API](https://developer.spotify.com/documentation/web-api) (your own app) |
| BRAT     | `BratModule`     | Written by hand: Brad's World of Warcraft rotation add-on ([code](https://github.com/bmfelix/BRAT)) |
| About    | `AboutModule`    | `Profile` and `Project` models, [GitHub API](https://docs.github.com/rest) (no key) |
| How it's built | `BuiltModule` | Written by hand, linked from the footer |

Modules can also give the homepage a live card instead of their summary. Each station has its own card showing the song on air, with **Listen live** and a song preview. WEBN's newest song can appear about a minute after it starts, so its card may briefly say "Last played".

## How it is built

- `hub/modules/base.py` defines `HubModule`, a class-based view. Each module subclasses it and returns its page data from `load()`.
- API modules keep their HTTP calls in a small client class (for example `OpenMeteoClient`). Tests swap that class for a fake, so they run without the internet.
- `hub/modules/__init__.py` holds the `MODULES` list. The menu, the homepage cards, and the URLs are all built from this list. To add a page, write a module class and a template, then add the class to the list.
- The menu collapses into a "Menu" button below 1040px wide.

## Live updates

The station cards on the homepage update without a reload:

1. The **listener** container (`python manage.py listen_radio`) asks both stations for their song every 15 seconds. The feeds cannot be subscribed to, so it polls.
2. When a song changes (or the current song ends), it renders the cards and sends them to the `radio` group through **Django Channels**, with **Redis** carrying the message between containers.
3. Each open homepage holds a WebSocket to `/ws/radio/` (`hub/consumers.py`), receives the new cards, and swaps them in (`hub/static/hub/live.js`).

Cards that need an outside service, such as weather and concerts, load after the page opens, so a slow service never holds it up. A module opts in with `live_card = True`, and `?card=1` returns just its card (`hub/static/hub/cards.js`).

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
  3. Log in at `/admin/`, then click **Connect Spotify** on the homepage.

The login renews itself. To disconnect, delete the Spotify account entry in the admin. Anyone who opens the site can see what you are playing.

## Other pages

- **Charts** counts every play the listener hears, per station and per week, in the `Play` model.
- **Concerts** lists Cincinnati, Dayton, and Columbus shows. Set `TICKETMASTER_API_KEY` in `.env`.
- **Agenda** reads calendars from `CALENDAR_URLS`. It needs a login by default. With `DJANGO_REQUIRE_LOGIN=0`, anyone who can reach the site can read your events.
- **Listening** shows top Spotify artists and tracks once Spotify is connected.
- **About** comes from `Profile` and `Project` in the admin, plus recent public GitHub work (`GITHUB_USERNAME`).
- **How it's built** compares the three builds and is linked from the footer.

## Going public

Before the site leaves your private network, set these in `.env`: `DJANGO_DEBUG=0`, a long random `DJANGO_SECRET_KEY`, and `DJANGO_SECURE_COOKIES=1`, which also means logging in only through an HTTPS address. Add the public address to `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.

Five wrong passwords lock a username from that address for an hour. To unlock sooner: `docker compose exec web python manage.py axes_reset`.

## Admin

To-dos and notes are read-only on the site: nobody can add, change, or delete them from those pages. Their data is meant to arrive from an outside API. Until then, they can be edited in the admin.

The agenda needs a login by default. Set `DJANGO_REQUIRE_LOGIN=0` in `.env` to open it to anyone who can reach the site, and to remove the login and admin links from the menu. The admin still needs a password: go to `/admin/` directly.

Create your login once: `docker compose exec web python manage.py createsuperuser`.

`/admin/` has full create, edit, and delete for tasks, notes, artists, radio names, songs, plays, and the About page:

- **Artists:** add one from just a MusicBrainz ID. Tick "keep my edits" so the 30-day refresh leaves your changes alone. A deleted artist comes back if the radio plays them again.
- **Radio names:** filter for empty artists to see names with no match, and pick the right artist to fix one.
- **Songs:** tick "keep my edits" the same way, or use the "Look up previews again" action.

## Keys and links

Everything here is optional. A feature without its setting explains itself on the page.

| Setting | Used for | Where to get it |
|---------|----------|-----------------|
| `SPOTIFY_PLAYLIST_URL` | The Spotify player on the homepage. Separate several with commas. | The share link of a public playlist |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | What is playing, and the Listening page | [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard). The app owner needs Spotify Premium. |
| `SPOTIFY_REDIRECT_URI` | Where Spotify returns after you connect | Add the same address to your Spotify app. Spotify does not accept `localhost`. |
| `TICKETMASTER_API_KEY` | Concerts | [developer.ticketmaster.com](https://developer.ticketmaster.com/) (the Consumer Key) |
| `CALENDAR_URLS` | Agenda. Separate several with commas. | Google: Settings > your calendar > Integrate calendar > **Secret address in iCal format**. Apple: turn on **Public Calendar**, then copy its share link. |
| `GITHUB_USERNAME` | Recent work on the About page | Your GitHub username |

Treat calendar links like passwords: anyone who has one can read that calendar.

`DJANGO_SITE_URL`, `NEXTJS_SITE_URL`, and `LARAVEL_SITE_URL` turn the headings on the How it's built page into links to each live site. A heading stays plain text if its address is empty.

## Design

All three builds share one look: a dark page with stage lights sweeping behind see-through cards, drifting music notes, and an equalizer under the current menu item. The homepage cards are numbered like the sides of an album. Fonts are Bricolage Grotesque, Instrument Sans, and Martian Mono from Google Fonts. Animations stop for visitors who ask their device to reduce motion.

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

Django 6.1 · Django Channels 4.3 · django-axes · Python 3.13 · Postgres 17 · Redis 8 · Uvicorn · WhiteNoise · iCalendar · Docker Compose
