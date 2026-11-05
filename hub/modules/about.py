import requests
from django.conf import settings
from django.core.cache import cache

from ..models import Profile, Project
from .base import HubModule

REPOS_URL = "https://api.github.com/users/{username}/repos"
CACHE_SECONDS = 60 * 60
REPOS_SHOWN = 6


class GitHubClient:
    timeout = 6

    def repos(self, username):
        response = requests.get(
            REPOS_URL.format(username=username), timeout=self.timeout,
            params={"sort": "pushed", "per_page": 30, "type": "owner"},
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        return response.json()


class AboutModule(HubModule):
    slug = "about"
    title = "About"
    summary = "Who made this, and what else they have built."
    on_home = False
    client_class = GitHubClient

    def repositories(self):
        """Recent public projects, skipping forks. GitHub being down only hides this section."""
        username = settings.GITHUB_USERNAME
        repos = cache.get("github-repos")
        if repos is None and username:
            try:
                repos = [repo for repo in self.client_class().repos(username) if not repo.get("fork")][:REPOS_SHOWN]
            except requests.RequestException:
                return []
            cache.set("github-repos", repos, CACHE_SECONDS)
        return repos or []

    def load(self):
        return {
            "profile": Profile.objects.first(),
            "projects": Project.objects.all(),
            "repositories": self.repositories(),
            "github_username": settings.GITHUB_USERNAME,
        }
