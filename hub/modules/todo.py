from ..models import Task
from .base import HubModule


class TodoModule(HubModule):
    """Shows tasks. They are read-only here: the data comes from elsewhere."""

    slug = "todo"
    title = "To-do"
    summary = "A simple task list."
    card_template = "hub/cards/todo.html"

    @classmethod
    def card(cls):
        tasks = Task.objects.filter(done=False)
        return {"open_tasks": tasks[:4], "open_count": tasks.count()}

    def load(self):
        return {"tasks": Task.objects.all()}
