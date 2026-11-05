import requests
from django import forms
from django.contrib import admin, messages

from .models import Artist, ArtistName, Note, Play, Profile, Project, Song, SpotifyAccount, Task
from .music import SongLibrary
from .musicbrainz import ArtistLibrary

admin.site.site_header = "Daily Hub"
admin.site.site_title = "Daily Hub"
admin.site.index_title = "Manage your content"
admin.site.site_url = "/"


@admin.register(Play)
class PlayAdmin(admin.ModelAdmin):
    list_display = ("played_at", "station", "artist_name", "title")
    list_filter = ("station",)
    search_fields = ("artist_name", "title")
    date_hierarchy = "played_at"
    exclude = ("song_key",)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "headline")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "tech", "order")
    list_editable = ("order",)


@admin.register(SpotifyAccount)
class SpotifyAccountAdmin(admin.ModelAdmin):
    """Delete the entry to disconnect Spotify. The login tokens are never shown."""

    fields = ("connected_at", "expires_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "done", "created_at")
    list_editable = ("done",)
    list_filter = ("done",)
    search_fields = ("title",)


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("title", "updated_at")
    search_fields = ("title", "body")


class ArtistAddForm(forms.ModelForm):
    """Add an artist from just their MusicBrainz ID. Everything else is fetched."""

    class Meta:
        model = Artist
        fields = ["mbid"]

    def clean_mbid(self):
        mbid = self.cleaned_data["mbid"]
        if Artist.objects.filter(mbid=mbid).exists():
            raise forms.ValidationError("That artist is already saved.")
        try:
            values = ArtistLibrary().fetch(str(mbid))
        except requests.RequestException as error:
            raise forms.ValidationError("MusicBrainz has no artist with that ID, or did not respond.") from error
        for field, value in values.items():
            setattr(self.instance, field, value)
        return mbid


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ("name", "has_wikipedia", "locked", "fetched_at")
    list_filter = ("locked",)
    search_fields = ("name", "mbid")
    readonly_fields = ("mbid", "fetched_at", "extras_checked_at")
    actions = ["refresh"]
    fieldsets = (
        (None, {"fields": ("name", "mbid", "locked", "fetched_at")}),
        ("Wikipedia", {"fields": ("wikipedia_title", "wikipedia_url", "wikipedia_summary", "wikipedia_image", "extras_checked_at")}),
        ("Saved data", {"classes": ("collapse",), "fields": ("data", "release_groups", "apple_albums")}),
    )

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields if obj else ()

    def get_fieldsets(self, request, obj=None):
        return self.fieldsets if obj else ((None, {"fields": ("mbid",)}),)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = ArtistAddForm
        return super().get_form(request, obj, **kwargs)

    @admin.display(boolean=True, description="Wikipedia")
    def has_wikipedia(self, artist):
        return bool(artist.wikipedia_summary)

    @admin.action(description="Refresh from MusicBrainz and Wikipedia")
    def refresh(self, request, queryset):
        library = ArtistLibrary()
        refreshed = skipped = 0
        for artist in queryset:
            if artist.locked:
                skipped += 1
                continue
            try:
                library.refresh(artist)
                refreshed += 1
            except requests.RequestException:
                self.message_user(request, f"Could not refresh {artist}.", messages.ERROR)
        self.message_user(request, f"Refreshed {refreshed}. Skipped {skipped} with saved edits.")


@admin.register(ArtistName)
class ArtistNameAdmin(admin.ModelAdmin):
    """Radio spellings. Pick an artist here to fix a wrong or missing match."""

    list_display = ("name", "artist", "checked_at")
    list_filter = (("artist", admin.EmptyFieldListFilter),)
    search_fields = ("name",)
    autocomplete_fields = ("artist",)
    fields = ("name", "artist", "checked_at")


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = ("title", "artist_name", "album", "has_preview", "locked", "checked_at")
    list_filter = ("locked",)
    search_fields = ("title", "artist_name", "album")
    autocomplete_fields = ("artist",)
    readonly_fields = ("checked_at",)
    actions = ["look_up_again"]

    @admin.display(boolean=True, description="Preview")
    def has_preview(self, song):
        return song.has_preview

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and not obj.has_preview:
            try:
                SongLibrary().look_up(obj)
            except requests.RequestException:
                self.message_user(request, "Saved, but the preview lookup failed.", messages.WARNING)

    @admin.action(description="Look up previews again")
    def look_up_again(self, request, queryset):
        library = SongLibrary()
        for song in queryset:
            try:
                library.look_up(song)
            except requests.RequestException:
                self.message_user(request, f"Could not look up {song}.", messages.ERROR)
                break
