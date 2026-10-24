from django import forms
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from ..models import Note
from .base import HubModule


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["title", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 8})}


class NotesModule(HubModule):
    slug = "notes"
    title = "Notes"
    summary = "Write, edit, and delete short notes."

    def current_note(self):
        note_id = self.request.GET.get("note") or self.request.POST.get("note")
        return get_object_or_404(Note, pk=note_id) if note_id else None

    def load(self):
        note = self.current_note()
        return {
            "notes": Note.objects.all(),
            "note": note,
            "form": getattr(self, "form", NoteForm(instance=note)),
        }

    def post(self, request, *args, **kwargs):
        note = self.current_note()
        if request.POST.get("action") == "delete" and note:
            note.delete()
            return redirect("hub:notes")

        self.form = NoteForm(request.POST, instance=note)
        if not self.form.is_valid():
            return self.get(request, *args, **kwargs)
        saved = self.form.save()
        return redirect(f"{reverse('hub:notes')}?note={saved.pk}")
