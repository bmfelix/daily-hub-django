from django.conf import settings

from .about import AboutModule
from .agenda import AgendaModule
from .brat import BratModule
from .built import BuiltModule
from .charts import ChartsModule
from .concerts import ConcertsModule
from .listening import ListeningModule
from .news import NewsModule
from .notes import NotesModule
from .radio import RadioModule
from .todo import TodoModule
from .weather import WeatherModule

# Menu order. Add a new module class here to give it a page and a menu link.
MODULES = [
    WeatherModule,
    NewsModule,
    TodoModule,
    NotesModule,
    AgendaModule,
    RadioModule,
    ChartsModule,
    ConcertsModule,
    ListeningModule,
    BratModule,
    AboutModule,
    BuiltModule,
]


def visible_modules(user):
    """The modules this person may see."""
    return [module for module in MODULES if not module.staff_only or user.is_staff or not settings.REQUIRE_LOGIN]
