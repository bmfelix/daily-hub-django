# Daily Hub · Django

A personal dashboard. Each menu link is one module, and each module is one class that calls its own API or database table.

This is one of three builds of the same app (Django, Next.js, Laravel), so the frameworks can be compared side by side.

## Modules

| Page     | Class            | Data source                                   |
|----------|------------------|-----------------------------------------------|
| Weather  | `WeatherModule`  | [Open-Meteo](https://open-meteo.com) (no key) |
| News     | `NewsModule`     | [Hacker News search API](https://hn.algolia.com/api) (no key) |
| To-do    | `TodoModule`     | Postgres (`Task` model)                       |
| Currency | `CurrencyModule` | [Frankfurter](https://frankfurter.dev) (no key) |
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

## Run with Docker

1. `cp .env.example .env` and set a secret key and database password.
2. `docker compose up -d --build`
3. Open http://localhost:8001

Optional admin login: `docker compose exec web python manage.py createsuperuser`, then visit `/admin/`.

Stop it with `docker compose down`.

## Tests

```sh
docker compose exec web python manage.py test
```

## Stack

Django 6.1 · Django Channels 4.3 · Python 3.13 · Postgres 17 · Redis 8 · Uvicorn · WhiteNoise · Docker Compose
