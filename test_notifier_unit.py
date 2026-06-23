import pytest
from core.notifier import NotificationService

def test_chunk_text_short():
    text = "Short message"
    chunks = NotificationService.chunk_text(text, limit=100)
    assert chunks == [text]

def test_chunk_text_long_split_newline():
    text = "Line 1\nLine 2\nLine 3"
    chunks = NotificationService.chunk_text(text, limit=10)
    assert len(chunks) == 3
    assert chunks[0] == "Line 1"
    assert chunks[1] == "Line 2"
    assert chunks[2] == "Line 3"

def test_clean_html():
    html_text = "<b>Bold</b> and <code>Code</code> with <pre>Pre</pre>"
    cleaned = NotificationService.clean_html(html_text)
    assert cleaned == "Bold and Code with Pre"
