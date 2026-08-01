"""A character's id must survive an edit (LOOM-45).

Once `events[].characters` and `relationships[].target` hold `wc-` ids, the id
IS the character as far as every other record is concerned. Regenerating one on
save would orphan every reference at once — the exact failure the migration away
from names was meant to end, arriving through a different door.

`put_writer_character` pins the id by assigning `body["id"] = char_id` before
storing, so the path parameter always wins over whatever the client sent. That
is one line and easy to lose in a refactor, which is why it is tested rather
than trusted.
"""

from server.routers.plan import put_writer_character


class _Store:
    """Stand-in for writer_store, so nothing on disk is touched."""

    def __init__(self, chars):
        self.chars = chars
        self.saved = None

    def writer_characters(self):
        return self.chars

    def save_writer_characters(self, value):
        self.saved = value


def _patched(monkeypatch, chars):
    store = _Store(chars)
    monkeypatch.setattr("server.routers.plan.writer_store", store)
    return store


def test_edit_keeps_the_id(monkeypatch):
    store = _patched(monkeypatch, [{"id": "wc-dcc1107a", "name": "Jared Gatlin"}])
    put_writer_character("wc-dcc1107a", {"id": "wc-dcc1107a", "name": "Jared Gatlin"})
    assert [c["id"] for c in store.saved] == ["wc-dcc1107a"]


def test_rename_keeps_the_id(monkeypatch):
    """The whole point: renaming must not mint a new identity."""
    store = _patched(monkeypatch, [{"id": "wc-dcc1107a", "name": "Jared Gatlin"}])
    put_writer_character("wc-dcc1107a", {"id": "wc-dcc1107a", "name": "Jared Renamed"})
    assert store.saved[0]["id"] == "wc-dcc1107a"
    assert store.saved[0]["name"] == "Jared Renamed"


def test_the_path_id_wins_over_the_body(monkeypatch):
    """A body claiming a different id must not move the character.

    Letting the two disagree would be a silent way to overwrite the wrong
    record — or to strand every reference pointing at the original id.
    """
    store = _patched(monkeypatch, [{"id": "wc-dcc1107a", "name": "Jared Gatlin"}])
    put_writer_character("wc-dcc1107a", {"id": "wc-somethingelse", "name": "Jared Gatlin"})
    assert [c["id"] for c in store.saved] == ["wc-dcc1107a"]


def test_unknown_id_appends_rather_than_404ing(monkeypatch):
    """The upsert half, which is how Loom's Characters tab creates a character."""
    store = _patched(monkeypatch, [{"id": "wc-existing", "name": "Someone"}])
    put_writer_character("wc-brandnew", {"name": "New Person"})
    assert [c["id"] for c in store.saved] == ["wc-existing", "wc-brandnew"]
