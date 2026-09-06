"""search_text is the single field BM25 and the vector index are built from.

Measured against zvec-grep on django, the skeleton form is where the losses
come from: 93% of the relevant symbols code-explorer failed to return were in
the index at median rank 179 of 200, because a prose query cannot match a
symbol whose relevance lives in its body -- and the body was never indexed.
See docs/explanation/gap-analysis-vs-zvec.md.

`body` mode must *append*, never substitute: the weighted-name prefix is what
keeps an identifier match above a prose match, and trading it away would swap
one failure mode for the other.
"""

import pytest

from code_explorer.graph.ingest import _derive_search_text
from code_explorer.settings import settings

SOURCE = '''def clear_cache(self):
    """Clear all internal caches."""
    self._expire_cache()
    for model in self.get_models():
        model._meta._expire_cache()
'''


@pytest.fixture
def restore_mode():
    original = settings.search_text_mode
    yield
    settings.search_text_mode = original


def _derive(**kwargs):
    return _derive_search_text(
        "django/apps/registry.py", "clear_cache", SOURCE,
        "Clear all internal caches.", ["_expire_cache", "get_models"], **kwargs
    )


def test_skeleton_is_unchanged_and_omits_the_body():
    text = _derive(mode="skeleton")

    assert text.startswith("django/apps/registry.py::clear_cache\nclear_cache\n")
    assert "clear cache\nclear cache" in text, "split words are emitted twice"
    assert "def clear_cache(self):" in text, "the signature is kept"
    assert "for model in self.get_models():" not in text, "the body is not indexed"


def test_body_mode_appends_rather_than_replaces(restore_mode):
    skeleton, body = _derive(mode="skeleton"), _derive(mode="body")

    assert body.startswith(skeleton), "the weighted-name prefix must survive intact"
    assert "for model in self.get_models():" in body


def test_body_is_capped_at_a_line_boundary(restore_mode):
    settings.search_text_mode = "body"
    settings.search_text_body_chars = 40
    try:
        text = _derive()
    finally:
        settings.search_text_body_chars = 2000

    appended = text[len(_derive(mode="skeleton")):]
    assert appended.strip(), "something was appended"
    assert not appended.endswith("mo"), "truncation lands on a line boundary"
    assert len(appended) <= 60


def test_mode_argument_overrides_the_setting(restore_mode):
    settings.search_text_mode = "skeleton"

    assert "self._expire_cache()" in _derive(mode="body")
    assert "self._expire_cache()" not in _derive()


def test_body_is_the_default():
    """Measured, not assumed -- see settings.search_text_mode for the table.

    Pinned by a test because flipping it back would silently undo the change
    that reached parity with zvec-grep, and nothing else would notice.
    """
    assert settings.model_fields["search_text_mode"].default == "body"
