from .currency import CurrencyModule
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
    CurrencyModule,
    NotesModule,
    RadioModule,
]
