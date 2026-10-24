from decimal import Decimal, InvalidOperation

import requests

from .base import HubModule

API_URL = "https://api.frankfurter.dev/v1"


class FrankfurterClient:
    """Talks to Frankfurter, a free exchange-rate API that needs no key."""

    timeout = 8

    def currencies(self):
        response = requests.get(f"{API_URL}/currencies", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def convert(self, amount, source, target):
        response = requests.get(
            f"{API_URL}/latest",
            params={"base": source, "symbols": target},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        rate = Decimal(str(data["rates"][target]))
        return {"rate": rate, "result": (amount * rate).quantize(Decimal("0.01")), "date": data["date"]}


class CurrencyModule(HubModule):
    slug = "currency"
    title = "Currency"
    summary = "Convert between currencies with today's exchange rates."

    client_class = FrankfurterClient

    def load(self):
        params = self.request.GET
        source = params.get("from", "USD")
        target = params.get("to", "EUR")
        raw_amount = params.get("amount", "100")
        context = {"source": source, "target": target, "amount": raw_amount}

        client = self.client_class()
        try:
            context["currencies"] = client.currencies()
        except requests.RequestException:
            context["error"] = "The exchange-rate service did not respond. Try again shortly."
            return context

        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            context["error"] = "Enter a number for the amount."
            return context
        if source not in context["currencies"] or target not in context["currencies"]:
            context["error"] = "Choose currencies from the list."
            return context
        if source == target:
            context["conversion"] = {"rate": Decimal(1), "result": amount, "date": None}
            return context

        try:
            context["conversion"] = client.convert(amount, source, target)
        except requests.RequestException:
            context["error"] = "The exchange-rate service did not respond. Try again shortly."
        return context
