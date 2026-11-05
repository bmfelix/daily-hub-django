from django.shortcuts import get_object_or_404

from ..models import Note
from .base import HubModule


class NotesModule(HubModule):
    """Shows notes. They are read-only here: the data comes from elsewhere."""

    slug = "notes"
    title = "Notes"
    summary = "Short notes to read."
    card_template = "hub/cards/notes.html"

    @classmethod
    def card(cls):
        return {"latest": Note.objects.first()}

    def load(self):
        note_id = self.request.GET.get("note")
        return {
            "notes": Note.objects.all(),
            "note": get_object_or_404(Note, pk=note_id) if note_id else None,
        }
