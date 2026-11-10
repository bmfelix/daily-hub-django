from datetime import datetime

import requests

from .base import HubModule

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REVERSE_GEOCODE_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "DailyHub/1.0"

# Countries and territories that report the weather in Fahrenheit.
FAHRENHEIT_COUNTRIES = {"US", "PR", "GU", "VI", "AS", "MP", "BS", "BZ", "KY", "LR", "PW", "FM", "MH"}

# WMO weather codes used by Open-Meteo, grouped into plain labels.
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Rain showers", 82: "Heavy rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def sky(code):
    """The kind of sky a weather code means, for the page's look and the day icons."""
    if code in (0, 1):
        return "clear"
    if code in (45, 48):
        return "fog"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    return "cloudy"


class OpenMeteoClient:
    """Talks to Open-Meteo, a free weather API that needs no key, and Nominatim for place names."""

    timeout = 8

    def find_place(self, name):
        response = requests.get(GEOCODE_URL, params={"name": name, "count": 1}, timeout=self.timeout)
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[0] if results else None

    def place_at(self, latitude, longitude):
        """Name the place at these coordinates. Open-Meteo cannot do this, so Nominatim does."""
        response = requests.get(
            REVERSE_GEOCODE_URL,
            params={
                "format": "jsonv2",
                "lat": latitude,
                "lon": longitude,
                "zoom": 10,
                "accept-language": "en",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        address = data.get("address")
        if not address:
            return None
        names = ("city", "town", "village", "hamlet", "municipality", "county", "state")
        return {
            "name": next((address[key] for key in names if address.get(key)), data.get("name")),
            "country": address.get("country"),
            "country_code": address.get("country_code", "").upper(),
            "latitude": latitude,
            "longitude": longitude,
        }

    def forecast(self, latitude, longitude, imperial=False):
        response = requests.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,apparent_temperature,wind_speed_10m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "forecast_days": 5,
                "temperature_unit": "fahrenheit" if imperial else "celsius",
                "wind_speed_unit": "mph" if imperial else "kmh",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


class WeatherModule(HubModule):
    slug = "weather"
    title = "Weather"
    summary = "Current conditions and a 5-day forecast for any city."
    live_card = True

    client_class = OpenMeteoClient
    default_city = "London"

    def coordinates(self):
        """Return the visitor's position from the URL, or None if it is missing or invalid."""
        try:
            latitude = float(self.request.GET.get("lat", ""))
            longitude = float(self.request.GET.get("lon", ""))
        except ValueError:
            return None
        return (latitude, longitude) if abs(latitude) <= 90 and abs(longitude) <= 180 else None

    def load(self):
        searched = self.request.GET.get("city", "").strip()
        coordinates = None if searched else self.coordinates()
        city = "" if coordinates else searched or self.default_city
        client = self.client_class()
        try:
            if coordinates:
                place = client.place_at(*coordinates)
                if place is None:
                    return {"city": city, "error": "No town found near your location."}
                city = place["name"]
            else:
                place = client.find_place(city)
                if place is None:
                    return {"city": city, "error": f"No place found called “{city}”."}
            imperial = place.get("country_code") in FAHRENHEIT_COUNTRIES
            data = client.forecast(place["latitude"], place["longitude"], imperial)
        except requests.RequestException:
            return {"city": city, "error": "The weather service did not respond. Try again shortly."}

        current = data["current"]
        daily = data["daily"]
        coldest = min(daily["temperature_2m_min"])
        spread = (max(daily["temperature_2m_max"]) - coldest) or 1
        days = [
            {
                "date": date,
                "weekday": datetime.strptime(date, "%Y-%m-%d").strftime("%a"),
                "label": WEATHER_CODES.get(code, "Unknown"),
                "sky": sky(code),
                "high": high,
                "low": low,
                # Where this day's range sits on a bar covering the whole week.
                "bar_start": round((low - coldest) / spread * 100),
                "bar_width": round((high - low) / spread * 100),
            }
            for date, code, high, low in zip(
                daily["time"], daily["weather_code"], daily["temperature_2m_max"], daily["temperature_2m_min"]
            )
        ]
        return {
            "city": city,
            "place": place,
            "temperature_unit": "°F" if imperial else "°C",
            "wind_unit": "mph" if imperial else "km/h",
            "current": {
                "temperature": current["temperature_2m"],
                "feels_like": current["apparent_temperature"],
                "wind": current["wind_speed_10m"],
                "label": WEATHER_CODES.get(current["weather_code"], "Unknown"),
                "sky": sky(current["weather_code"]),
            },
            "days": days,
        }
