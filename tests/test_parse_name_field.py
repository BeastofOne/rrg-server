"""Tests for parse_name_field — extracted from gmail_pubsub_webhook.py.

The function is copied here for isolated unit testing (it only depends on `re`).
"""

import re
import pytest


# ---------------------------------------------------------------------------
# Function under test (copied from windmill/f/switchboard/gmail_pubsub_webhook.py
# lines 459-492 — standalone, only depends on `re`)
# ---------------------------------------------------------------------------

def parse_name_field(body, subject=""):
    """Extract a person's name from notification body text."""
    # "Name: John Doe" pattern (capitalized)
    m = re.search(
        r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([A-Z][a-zA-Z\'\-]+(?:[ \t]+[A-Z][a-zA-Z\'\-]+){0,3})',
        body
    )
    if m:
        return m.group(1).strip()
    # Case-insensitive fallback
    m = re.search(
        r'(?:name|contact|buyer|seller|lead)\s*[:\-]\s*([a-zA-Z\'\-]+(?:[ \t]+[a-zA-Z\'\-]+){0,3})',
        body, re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        skip = {'the', 'a', 'an', 'your', 'this', 'that', 'none', 'n/a', 'not', 'no'}
        if len(name) > 1 and name.lower() not in skip:
            return name
    # Subject line fallback
    if subject:
        m = re.match(
            r'([A-Z][a-zA-Z\'\-]+(?:\s+[A-Z][a-zA-Z\'\-]+){1,3})\s+(?:has\s+)?(?:opened|executed|requesting|downloaded|favorited|clicked|is\s+requesting)',
            subject, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()
    return ""


# ===========================================================================
# 1. Regression: BizBuySell \r\n bleed-across-lines bug
# ===========================================================================

class TestRegressionNewlineBleed:
    """The original bug: \\s+ in word-separator matched newlines, causing the
    name capture to bleed across lines into subsequent fields."""

    def test_bizbuysell_contact_crlf(self):
        """Exact body from the BizBuySell email that triggered the bug."""
        body = "Contact: Jon C\r\n \n\r\n \r\nContact Email: lttc.digital@gmail.com"
        assert parse_name_field(body) == "Jon C"

    def test_name_followed_by_lf(self):
        body = "Name: Alice Smith\nEmail: alice@example.com"
        assert parse_name_field(body) == "Alice Smith"

    def test_name_followed_by_crlf(self):
        body = "Name: Alice Smith\r\nEmail: alice@example.com"
        assert parse_name_field(body) == "Alice Smith"

    def test_name_followed_by_double_newline(self):
        body = "Name: Bob Jones\n\nPhone: 555-1234"
        assert parse_name_field(body) == "Bob Jones"

    def test_name_does_not_bleed_into_next_label(self):
        """Even with whitespace between lines, name must stop at line boundary."""
        body = "Contact: Maria\r\n  \r\nContact Email: maria@test.com"
        assert parse_name_field(body) == "Maria"


# ===========================================================================
# 2. Normal cases — standard labeled name patterns
# ===========================================================================

class TestNormalCases:
    def test_name_colon(self):
        assert parse_name_field("Name: John Smith") == "John Smith"

    def test_contact_colon(self):
        assert parse_name_field("Contact: Jane Doe") == "Jane Doe"

    def test_buyer_colon(self):
        assert parse_name_field("Buyer: Sarah Johnson") == "Sarah Johnson"

    def test_seller_colon(self):
        assert parse_name_field("Seller: Mike Brown") == "Mike Brown"

    def test_lead_dash(self):
        assert parse_name_field("Lead - Sarah Johnson") == "Sarah Johnson"

    def test_lead_colon(self):
        assert parse_name_field("Lead: Carlos Garcia") == "Carlos Garcia"

    def test_name_with_hyphen(self):
        assert parse_name_field("Name: Anne-Marie O'Brien") == "Anne-Marie O'Brien"

    def test_name_with_apostrophe(self):
        assert parse_name_field("Name: Patrick O'Malley") == "Patrick O'Malley"

    def test_three_part_name(self):
        assert parse_name_field("Name: Mary Jane Watson") == "Mary Jane Watson"

    def test_four_part_name(self):
        """Up to 4 capitalized words should be captured (initial + {0,3})."""
        assert parse_name_field("Name: Mary Jane Watson Smith") == "Mary Jane Watson Smith"

    def test_single_name(self):
        assert parse_name_field("Name: Madonna") == "Madonna"

    def test_label_no_space_after_colon(self):
        assert parse_name_field("Name:John Smith") == "John Smith"

    def test_label_extra_space_after_colon(self):
        assert parse_name_field("Name:   John Smith") == "John Smith"


# ===========================================================================
# 3. Multiline bodies — name on one line, other fields on subsequent lines
# ===========================================================================

class TestMultilineBodies:
    def test_typical_lead_email_body(self):
        body = (
            "You have a new lead!\n"
            "Name: David Lee\n"
            "Email: david@example.com\n"
            "Phone: (734) 555-1234\n"
            "Message: I'm interested in the property."
        )
        assert parse_name_field(body) == "David Lee"

    def test_crlf_lead_email_body(self):
        body = (
            "New lead notification\r\n"
            "Contact: Emily Chen\r\n"
            "Contact Email: emily@test.com\r\n"
            "Phone: 555-9876\r\n"
        )
        assert parse_name_field(body) == "Emily Chen"

    def test_mixed_newlines(self):
        body = "Buyer: Frank Williams\r\n\nSeller: Someone Else\nDeal: 123"
        assert parse_name_field(body) == "Frank Williams"

    def test_name_buried_in_long_body(self):
        body = (
            "Property Alert\n"
            "================\n"
            "A new inquiry has been received.\n\n"
            "Lead: Rachel Green\n"
            "Source: Crexi\n"
            "Property: 123 Main St\n"
            "Notes: Interested in office space\n"
        )
        assert parse_name_field(body) == "Rachel Green"


# ===========================================================================
# 4. Subject line fallback
# ===========================================================================

class TestSubjectFallback:
    def test_subject_opened(self):
        r"""Note: with re.IGNORECASE the greedy {1,3} captures 'has' as a name
        word before the optional (?:has\s+)? can consume it.  Real-world
        subjects like 'John Smith opened ...' (without 'has') work cleanly."""
        result = parse_name_field("", subject="John Smith opened your listing")
        assert result == "John Smith"

    def test_subject_has_opened_greedy(self):
        """Documents current greedy capture: 'has' is swallowed into the name
        group because re.IGNORECASE makes [A-Z] match lowercase 'h'."""
        result = parse_name_field("", subject="John Smith has opened your listing")
        assert result == "John Smith has"

    def test_subject_executed(self):
        result = parse_name_field("", subject="Jane Doe executed the NDA")
        assert result == "Jane Doe"

    def test_subject_requesting(self):
        result = parse_name_field("", subject="Bob Williams requesting information")
        assert result == "Bob Williams"

    def test_subject_is_requesting(self):
        r"""Same greedy-capture issue as 'has opened': 'is' gets captured as a
        name word.  The (?:is\s+requesting) alternative still matches after
        the name group consumes 'is', because the outer alternation sees
        'requesting' directly."""
        result = parse_name_field("", subject="Alice Brown is requesting a tour")
        assert result == "Alice Brown is"

    def test_subject_downloaded(self):
        result = parse_name_field("", subject="Carlos Garcia downloaded the brochure")
        assert result == "Carlos Garcia"

    def test_subject_favorited(self):
        result = parse_name_field("", subject="Maria Lopez favorited your listing")
        assert result == "Maria Lopez"

    def test_subject_clicked(self):
        result = parse_name_field("", subject="Tom Anderson clicked on your listing")
        assert result == "Tom Anderson"

    def test_body_takes_priority_over_subject(self):
        """When body has a labeled name, subject should not be used."""
        body = "Name: Body Name"
        subject = "Subject Name has opened your listing"
        assert parse_name_field(body, subject=subject) == "Body Name"

    def test_subject_not_used_when_body_has_name(self):
        """Even case-insensitive body match beats subject.  The fallback
        regex captures both words ('lowercase name') since {0,3} allows
        additional words separated by [ \\t]+."""
        body = "name: lowercase name"
        subject = "Other Person has opened your listing"
        assert parse_name_field(body, subject=subject) == "lowercase name"

    def test_subject_no_action_verb(self):
        """Subject without a recognized action verb should not match."""
        result = parse_name_field("", subject="John Smith sent you a message")
        assert result == ""


# ===========================================================================
# 5. Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_empty_body_empty_subject(self):
        assert parse_name_field("") == ""
        assert parse_name_field("", subject="") == ""

    def test_no_labeled_name_in_body_no_subject(self):
        assert parse_name_field("Just some random text with no name label.") == ""

    def test_skip_word_the(self):
        assert parse_name_field("name: the") == ""

    def test_skip_word_none(self):
        assert parse_name_field("name: none") == ""

    def test_skip_word_na(self):
        assert parse_name_field("name: n/a") == ""

    def test_skip_word_not(self):
        assert parse_name_field("name: not") == ""

    def test_skip_word_no(self):
        assert parse_name_field("name: no") == ""

    def test_skip_word_your(self):
        assert parse_name_field("name: your") == ""

    def test_skip_word_this(self):
        assert parse_name_field("name: this") == ""

    def test_skip_word_that(self):
        assert parse_name_field("name: that") == ""

    def test_skip_word_a(self):
        """Single character 'a' is skipped by len(name) > 1 check."""
        assert parse_name_field("name: a") == ""

    def test_skip_word_an(self):
        assert parse_name_field("name: an") == ""

    def test_case_insensitive_label(self):
        assert parse_name_field("NAME: John Smith") == "John Smith"

    def test_mixed_case_label(self):
        assert parse_name_field("Name: John Smith") == "John Smith"

    def test_lowercase_name_value(self):
        """Lowercase name matches via case-insensitive fallback.  Both words
        are captured because {0,3} allows additional space-separated words."""
        result = parse_name_field("name: john smith")
        assert result == "john smith"

    def test_tab_separated_name_parts(self):
        """Tab between name parts should be allowed by [ \\t]+."""
        assert parse_name_field("Name: John\tSmith") == "John\tSmith"

    def test_name_with_trailing_whitespace(self):
        result = parse_name_field("Name: John Smith   ")
        assert result == "John Smith"

    def test_body_with_only_whitespace(self):
        assert parse_name_field("   \n\t  ") == ""

    def test_label_at_end_of_body_no_value(self):
        """Label with no name after it should not match."""
        assert parse_name_field("Name:") == ""

    def test_label_with_newline_immediately_after(self):
        """Label followed by newline: the \\s* after the colon crosses the
        newline boundary, then 'Email' (capitalized) matches as a name.
        This is a known quirk — in practice, real emails always have the
        name value on the same line as the label."""
        assert parse_name_field("Name:\nEmail: test@test.com") == "Email"

    def test_label_with_newline_then_lowercase(self):
        """When the next line starts lowercase, the capitalized-first regex
        fails, and the case-insensitive fallback captures the lowercase word.
        With 'email' being a non-skip word, it returns 'email'."""
        assert parse_name_field("name:\nemail: test@test.com") == "email"


# ===========================================================================
# 6. Newline-bleed coverage for case-insensitive fallback (line 474 fix)
# ===========================================================================

class TestFallbackNewlineBleed:
    """The [ \\t]+ fix was applied to BOTH regex patterns. These tests verify
    the case-insensitive fallback (second regex) also stops at newlines."""

    def test_lowercase_name_no_bleed_lf(self):
        """Lowercase name should not bleed across \\n into next field."""
        body = "name: jon c\ncontact email: lttc@gmail.com"
        assert parse_name_field(body) == "jon c"

    def test_lowercase_name_no_bleed_crlf(self):
        """Lowercase name should not bleed across \\r\\n."""
        body = "name: jon c\r\ncontact email: lttc@gmail.com"
        assert parse_name_field(body) == "jon c"

    def test_lowercase_bizbuysell_exact_pattern(self):
        """BizBuySell-style body with lowercase name hitting fallback regex."""
        body = "contact: jon c\r\n \n\r\n \r\ncontact email: lttc@gmail.com"
        assert parse_name_field(body) == "jon c"

    def test_lowercase_single_word_no_bleed(self):
        """Single lowercase word should not grab next line's text."""
        body = "name: maria\r\nemail: maria@test.com"
        assert parse_name_field(body) == "maria"


# ===========================================================================
# 7. Word-separator edge cases ([ \t]+ only matches space and tab)
# ===========================================================================

class TestWordSeparatorEdgeCases:
    """Verify that only spaces and tabs count as word separators,
    and other whitespace characters do not."""

    def test_multiple_spaces_between_words(self):
        """Multiple spaces between name parts should still be captured."""
        assert parse_name_field("Name: John   Smith") == "John   Smith"

    def test_mixed_space_tab_between_words(self):
        """Mixed space+tab between name parts should still be captured."""
        assert parse_name_field("Name: John \tSmith") == "John \tSmith"

    def test_vertical_tab_not_a_word_separator(self):
        """Vertical tab (\\v) is matched by \\s but not by [ \\t].
        The name should stop before the vertical tab."""
        body = "Name: John\vSmith"
        assert parse_name_field(body) == "John"

    def test_form_feed_not_a_word_separator(self):
        """Form feed (\\f) is matched by \\s but not by [ \\t].
        The name should stop before the form feed."""
        body = "Name: John\fSmith"
        assert parse_name_field(body) == "John"

    def test_single_name_followed_by_newline_then_capitalized_word(self):
        """A single capitalized name should NOT pick up the next line's
        capitalized text as part of the name."""
        body = "Name: Madonna\nAddress: 123 Main St"
        assert parse_name_field(body) == "Madonna"
