from .base import HubModule


class BuiltModule(HubModule):
    slug = "built"
    title = "How it's built"
    summary = "One app, built three times to compare the frameworks."
    in_menu = False
    on_home = False
