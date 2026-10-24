from django.views.generic import TemplateView


class HubModule(TemplateView):
    """One Daily Hub page. Each subclass is one menu link and owns its API calls."""

    slug = ""
    title = ""
    summary = ""
    card_template = "hub/cards/summary.html"

    def get_template_names(self):
        return [f"hub/modules/{self.slug}.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["module"] = self
        context.update(self.load())
        return context

    def load(self):
        """Return extra template context. Subclasses call their API here."""
        return {}

    @classmethod
    def card(cls):
        """Return context for this module's homepage card. Override to show live data."""
        return {}
