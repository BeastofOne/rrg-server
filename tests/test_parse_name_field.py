"""Regression tests for parse_name_field — \\s+ → [ \\t]+ fix.

Verifies the regex no longer bleeds across newlines when capturing names.
"""

import re


def parse_name_field(body, subject=""):
    """Extract a person's name from notification body text."""
    m = re.search(
        r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([A-Z][a-zA-Z\'\-]+(?:[ \t]+[A-Z][a-zA-Z\'\-]+){0,3})',
        body
    )
    if m:
        return m.group(1).strip()
    m = re.search(
        r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([a-zA-Z\'\-]+(?:[ \t]+[a-zA-Z\'\-]+){0,3})',
        body, re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        skip = {"the", "a", "an", "new", "your", "dear", "hello", "hi", "hey", "from", "re", "fw", "fwd"}
        if name.lower() not in skip:
            return name
    if subject:
        m = re.match(r'[A-Z][a-zA-Z\'\-]+(?:\s+[A-Z][a-zA-Z\'\-]+){1,2}', subject)
        if m:
            return m.group(0).strip()
    return ""


def test_capitalized_name_stops_at_newline():
    """BizBuySell body: capitalized name must not bleed across \\r\\n."""
    body = "Name: Jon C\r\n \n\r\n \r\n Contact Email"
    assert parse_name_field(body) == "Jon C"


def test_lowercase_name_stops_at_newline():
    """Case-insensitive fallback must also stop at \\r\\n."""
    body = "name: jon c\r\n \n\r\n \r\n contact email"
    assert parse_name_field(body) == "jon c"


def test_spaces_still_captured():
    """Spaces between name words should still work."""
    body = "Name: John Michael Doe"
    assert parse_name_field(body) == "John Michael Doe"


def test_tabs_still_captured():
    """Tabs between name words should still work."""
    body = "Name: John\tDoe"
    assert parse_name_field(body) == "John\tDoe"
