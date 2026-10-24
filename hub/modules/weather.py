import requests

from .base import HubModule

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

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


class OpenMeteoClient:
    """Talks to Open-Meteo, a free weather API that needs no key."""

    timeout = 8

    def find_place(self, name):
        response = requests.get(GEOCODE_URL, params={"name": name, "count": 1}, timeout=self.timeout)
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[0] if results else None

    def forecast(self, latitude, longitude):
        response = requests.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,apparent_temperature,wind_speed_10m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "forecast_days": 5,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


class WeatherModule(HubModule):
    slug = "weather"
    title = "Weather"
    summary = "Current conditions and a 5-day forecast for any city."

    client_class = OpenMeteoClient
    default_city = "London"

    def load(self):
        city = self.request.GET.get("city", "").strip() or self.default_city
        client = self.client_class()
        try:
            place = client.find_place(city)
            if place is None:
                return {"city": city, "error": f"No place found called “{city}”."}
            data = client.forecast(place["latitude"], place["longitude"])
        except requests.RequestException:
            return {"city": city, "error": "The weather service did not respond. Try again shortly."}

        current = data["current"]
        daily = data["daily"]
        days = [
            {
                "date": date,
                "label": WEATHER_CODES.get(code, "Unknown"),
                "high": high,
                "low": low,
            }
            for date, code, high, low in zip(
                daily["time"], daily["weather_code"], daily["temperature_2m_max"], daily["temperature_2m_min"]
            )
        ]
        return {
            "city": city,
            "place": place,
            "current": {
                "temperature": current["temperature_2m"],
                "feels_like": current["apparent_temperature"],
                "wind": current["wind_speed_10m"],
                "label": WEATHER_CODES.get(current["weather_code"], "Unknown"),
            },
            "days": days,
        }
