from urllib.parse import quote

from django.db import models

from .names import song_key


class Task(models.Model):
    title = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "-created_at"]

    def __str__(self):
        return self.title


class Note(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class Artist(models.Model):
    """Everything MusicBrainz has on one artist, saved so it is fetched only once."""

    mbid = models.UUIDField("MusicBrainz ID", unique=True)
    name = models.CharField(max_length=300)
    data = models.JSONField(help_text="The full MusicBrainz artist record.")
    release_groups = models.JSONField(default=list, blank=True, help_text="Every album, EP, and single.")
    fetched_at = models.DateTimeField()
    locked = models.BooleanField(
        "keep my edits", default=False, help_text="Stops the automatic refresh from replacing this artist's details.",
    )
    wikipedia_title = models.CharField(max_length=300, blank=True)
    wikipedia_url = models.URLField(max_length=500, blank=True)
    wikipedia_summary = models.TextField(blank=True, help_text="The opening text of the Wikipedia page.")
    wikipedia_image = models.URLField(max_length=500, blank=True, help_text="The page's freely licensed lead photo.")
    apple_albums = models.JSONField(default=dict, blank=True, help_text="Apple artwork and links, used when the Cover Art Archive has no cover.")
    extras_checked_at = models.DateTimeField(null=True, blank=True, help_text="When Wikipedia and Apple were last checked.")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ArtistName(models.Model):
    """A name as the radio spells it, and the artist it matched (or none)."""

    key = models.CharField(max_length=300, unique=True, help_text="The name in lowercase.")
    name = models.CharField(max_length=300)
    artist = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.CASCADE, related_name="names")
    checked_at = models.DateTimeField()

    def save(self, *args, **kwargs):
        self.key = self.name.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Play(models.Model):
    """One song heard on one station. The charts are counted from these."""

    station = models.CharField(max_length=40)
    artist_name = models.CharField(max_length=300)
    title = models.CharField(max_length=300)
    song_key = models.CharField(max_length=400, db_index=True)
    played_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-played_at"]
        constraints = [models.UniqueConstraint(fields=["station", "played_at"], name="one_song_at_a_time")]

    def __str__(self):
        return f"{self.station}: {self.artist_name} – {self.title}"


class Profile(models.Model):
    """The About page's introduction. Only the first one is shown."""

    name = models.CharField(max_length=200)
    headline = models.CharField(max_length=300, blank=True)
    bio = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True, help_text="Shown publicly. Leave empty to keep it private.")

    def __str__(self):
        return self.name


class Project(models.Model):
    """Work to show on the About page."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    tech = models.CharField(max_length=300, blank=True, help_text="Separate with commas.")
    url = models.URLField("live link", blank=True)
    repo_url = models.URLField("code link", blank=True)
    order = models.PositiveIntegerField(default=0, help_text="Lower numbers show first.")

    class Meta:
        ordering = ["order", "title"]

    @property
    def tech_list(self):
        return [item.strip() for item in self.tech.split(",") if item.strip()]

    def __str__(self):
        return self.title


class SpotifyAccount(models.Model):
    """The site owner's Spotify login. There is only ever one."""

    access_token = models.TextField()
    refresh_token = models.TextField()
    expires_at = models.DateTimeField()
    connected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Connected {self.connected_at:%b %d, %Y}"


class Song(models.Model):
    """A song heard on the radio, with where to preview it. Each is looked up once."""

    key = models.CharField(max_length=400, unique=True, editable=False, help_text="Artist and title, compared loosely.")
    title = models.CharField(max_length=300)
    artist_name = models.CharField("artist", max_length=300, help_text="The name as the radio spells it.")
    artist = models.ForeignKey(
        Artist, null=True, blank=True, on_delete=models.SET_NULL, related_name="songs", verbose_name="artist page",
    )
    album = models.CharField(max_length=300, blank=True)
    artwork_url = models.URLField(max_length=500, blank=True)
    apple_preview_url = models.URLField(max_length=500, blank=True)
    apple_url = models.URLField("Apple Music link", max_length=500, blank=True)
    deezer_track_id = models.BigIntegerField(null=True, blank=True)
    deezer_url = models.URLField("Deezer link", max_length=500, blank=True)
    locked = models.BooleanField(
        "keep my edits", default=False, help_text="Stops the automatic refresh from replacing this song's details.",
    )
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["artist_name", "title"]

    def save(self, *args, **kwargs):
        self.key = song_key(self.artist_name, self.title)
        super().save(*args, **kwargs)

    @property
    def has_preview(self):
        return bool(self.apple_preview_url or self.deezer_track_id)

    @property
    def spotify_url(self):
        return f"https://open.spotify.com/search/{quote(f'{self.artist_name} {self.title}')}"

    @property
    def youtube_music_url(self):
        return f"https://music.youtube.com/search?q={quote(f'{self.artist_name} {self.title}')}"

    def __str__(self):
        return f"{self.artist_name} – {self.title}"
