from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse
from django.views.generic import TemplateView


class HubModule(TemplateView):
    """One Daily Hub page. Each subclass is one menu link and owns its API calls."""

    slug = ""
    title = ""
    summary = ""
    card_template = "hub/cards/summary.html"
    live_card = False  # True: the homepage loads this module's own card after the page opens
    in_menu = True
    on_home = True
    staff_only = False  # True: only someone logged in can see it at all

    def dispatch(self, request, *args, **kwargs):
        """Staff-only pages need a login. No page changes anything, so posts are turned away."""
        needs_login = request.method == "POST" or self.staff_only
        if needs_login and settings.REQUIRE_LOGIN and not request.user.is_staff:
            return redirect_to_login(request.get_full_path(), reverse("admin:login"))
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        if self.live_card and "card" in self.request.GET:
            return [f"hub/cards/{self.slug}_live.html"]
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
