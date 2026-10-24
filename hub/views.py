from django.shortcuts import render

from .modules import MODULES


def home(request):
    cards = [{"module": module, "template": module.card_template, **module.card()} for module in MODULES]
    return render(request, "hub/home.html", {"cards": cards})
