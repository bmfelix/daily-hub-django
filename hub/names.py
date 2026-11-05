"""Comparing the names radio stations and music services use."""

import re
import unicodedata

# Separators the stations use between several artists, as in "Tame Impala [+] Jennie".
SEPARATORS = re.compile(r"\s*(?:\[\+\]|,|&|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\bx\b|/)\s*", re.I)


def normalize(name):
    """Compare names loosely: no accents, case, or punctuation."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def compact(name):
    """Like normalize, and ignores spaces too, so "3AM" and "3 AM" are the same."""
    return normalize(name).replace(" ", "")


def name_candidates(name):
    """The full name first (for duos like "Simon & Garfunkel"), then the first listed artist."""
    name = name.strip()
    first = SEPARATORS.split(name, maxsplit=1)[0].strip()
    return [name] if first in ("", name) else [name, first]


def song_key(artist, title):
    """The same song however a station spells it."""
    return f"{compact(artist)}|{compact(title)}"[:400]
