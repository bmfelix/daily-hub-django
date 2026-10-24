from django import forms
from django.shortcuts import get_object_or_404, redirect

from ..models import Task
from .base import HubModule


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["title"]


class TodoModule(HubModule):
    slug = "todo"
    title = "To-do"
    summary = "A simple task list saved in the database."

    def load(self):
        return {"tasks": Task.objects.all(), "form": getattr(self, "form", TaskForm())}

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "add":
            self.form = TaskForm(request.POST)
            if not self.form.is_valid():
                return self.get(request, *args, **kwargs)
            self.form.save()
        elif action in ("toggle", "delete"):
            task = get_object_or_404(Task, pk=request.POST.get("task"))
            if action == "toggle":
                task.done = not task.done
                task.save(update_fields=["done"])
            else:
                task.delete()
        return redirect("hub:todo")
