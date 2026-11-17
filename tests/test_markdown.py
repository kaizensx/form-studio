"""Markdown → Qt rich text (form/app/markdown.py): what a reply is turned into before the interface draws it.
Pure text: no Qt, no display."""
import re
import unittest

from form.app import markdown as md


def strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class Parse(unittest.TestCase):
    def test_paragraphs_and_headings(self):
        b = md.parse("# Title\n\nOne line\nsame paragraph\n\nNext")
        self.assertEqual([x["t"] for x in b], ["h", "p", "p"])
        self.assertEqual((b[0]["level"], b[0]["text"]), (1, "Title"))
        self.assertEqual(b[1]["text"], "One line\nsame paragraph")

    def test_bullets_numbers_and_nesting(self):
        b = md.parse("1. one\n2. two\n   - a\n   - b\n     - deep\n3. three\n\n- x\n- y")
        self.assertEqual([x["t"] for x in b], ["list", "list"])
        num, bul = b
        self.assertTrue(num["ordered"])
        self.assertFalse(bul["ordered"])
        self.assertEqual(len(num["items"]), 3)
        inner = num["items"][1]["blocks"]
        self.assertEqual([x["t"] for x in inner], ["p", "list"])
        self.assertEqual(len(inner[1]["items"]), 2)
        deep = inner[1]["items"][1]["blocks"][1]
        self.assertEqual((deep["t"], deep["items"][0]["blocks"][0]["text"]), ("list", "deep"))

    def test_two_space_nesting_and_start_number(self):
        b = md.parse("- a\n  - b\n\n7. seven\n8. eight")
        self.assertEqual(b[0]["items"][0]["blocks"][1]["t"], "list")
        self.assertEqual(b[1]["start"], 7)
        self.assertIn(">7.<", md.to_html("7. seven\n8. eight"))

    def test_loose_list_and_a_second_paragraph_in_an_item(self):
        b = md.parse("- first\n\n  more of the first\n\n- second")
        self.assertEqual(len(b), 1)
        self.assertTrue(b[0]["loose"])
        self.assertEqual([x["t"] for x in b[0]["items"][0]["blocks"]], ["p", "p"])

    def test_a_long_item_continues_on_the_next_line(self):
        b = md.parse("- a long item\nthat was wrapped by hand\n- next")
        self.assertEqual(b[0]["items"][0]["blocks"][0]["text"], "a long item\nthat was wrapped by hand")
        self.assertEqual(len(b[0]["items"]), 2)

    def test_code_fences_keep_their_text(self):
        b = md.parse("```python\nx = 1\n  - not a list\n**not bold**\n```\nafter")
        self.assertEqual((b[0]["t"], b[0]["lang"]), ("code", "python"))
        self.assertEqual(b[0]["text"], "x = 1\n  - not a list\n**not bold**")
        self.assertEqual(b[1]["text"], "after")
        html = md.to_html("```\na < b && **c**\n```")
        self.assertIn("a &lt; b &amp;&amp; **c**", html)
        self.assertIn("white-space:pre-wrap", html)

    def test_table(self):
        b = md.parse("| A | B |\n|---|--:|\n| 1 | 2 |\n| 3 |\n\ntail")
        t = b[0]
        self.assertEqual((t["t"], t["head"], t["align"]), ("table", ["A", "B"], ["left", "right"]))
        self.assertEqual(t["rows"], [["1", "2"], ["3", ""]])
        html = md.to_html("| A | B |\n|---|--:|\n| 1 | `2` |")
        self.assertIn('<th align="left"', html)
        self.assertIn('<td align="right"', html)

    def test_quote_and_rule(self):
        b = md.parse("> quoted\n> more\n\n---\n\nend")
        self.assertEqual([x["t"] for x in b], ["quote", "hr", "p"])
        self.assertEqual(b[0]["blocks"][0]["text"], "quoted\nmore")

    def test_task_items(self):
        b = md.parse("- [x] done\n- [ ] open")
        self.assertEqual([i["task"] for i in b[0]["items"]], [True, False])


class Inline(unittest.TestCase):
    def test_emphasis_code_and_links(self):
        h = md.inline("**bold** and *it* and _it_ and `a*b*` and [text](https://x.example/a?b=1&c=2) ~~gone~~")
        self.assertIn("<b>bold</b>", h)
        self.assertEqual(h.count("<i>it</i>"), 2)
        self.assertIn("a*b*", h)
        self.assertIn('<a href="https://x.example/a?b=1&amp;c=2">text</a>', h)
        self.assertIn("<s>gone</s>", h)

    def test_everything_from_the_agent_is_escaped(self):
        h = md.to_html('<img src=x onerror=1> & <b>raw</b> [l](" onclick="x)')
        self.assertNotIn("<img", h)
        self.assertNotIn("<b>raw", h)
        self.assertIn("&lt;img", h)
        self.assertNotRegex(h, r'href="[^"]*"[^>]*onclick="')

    def test_unfinished_markers_stay_text(self):
        # a reply is drawn while it is being written: half a marker must not swallow or break anything
        for partial in ("**bol", "a `code", "[link](http", "snake_case_name and 2 * 3 * 4", "~~x"):
            self.assertEqual(strip(md.to_html(partial)), partial)

    def test_bare_and_angle_links(self):
        h = md.inline("see https://example.com/a. and <https://example.com/b>")
        self.assertIn('<a href="https://example.com/a">https://example.com/a</a>.', h)
        self.assertIn('<a href="https://example.com/b">', h)

    def test_link_colour_comes_from_the_style(self):
        self.assertIn('style="color:#abcdef;"', md.to_html("[a](https://b.example)", {"link": "#abcdef"}))


class Layout(unittest.TestCase):
    """The reason this module exists: lists on the app's 8 px grid, with hanging indents and a small, even step."""

    def test_no_qt_list_elements(self):
        h = md.to_html("- a\n- b\n\n1. c\n   - d")
        for tag in ("<ul", "<ol", "<li"):
            self.assertNotIn(tag, h)

    def test_marker_column_is_on_the_grid_and_text_hangs_beside_it(self):
        h = md.to_html("- a long item that wraps onto a second line in a narrow column")
        m = re.search(r'<tr><td width="(\d+)" valign="top"><span[^>]*>•</span></td><td valign="top">', h)
        self.assertIsNotNone(m, h)
        self.assertEqual(int(m.group(1)), md.STEP)
        self.assertEqual(md.STEP % 8, 0)

    def test_number_column_grows_by_whole_grid_steps(self):
        widths = {}
        for n in (3, 12):
            h = md.to_html("\n".join("%d. x" % (i + 1) for i in range(n)))
            widths[n] = {int(w) for w in re.findall(r'<td width="(\d+)" valign="top"', h)}
        self.assertEqual(widths[3], {24})
        self.assertEqual(widths[12], {32})
        for w in (24, 32):
            self.assertEqual(w % 8, 0)

    def test_nested_lists_step_by_one_marker_column(self):
        h = md.to_html("- a\n  - b\n    - c")
        self.assertEqual(h.count('<table width="100%"'), 3, "each level fills its parent's text cell, so it wraps at the column edge")
        self.assertEqual(h.count("<table"), 3)                       # each level is a table inside its parent's text cell
        self.assertEqual(set(re.findall(r'<td width="(\d+)"', h)), {str(md.STEP)})
        self.assertNotIn("margin-left", h)

    def test_first_block_has_no_gap_above_and_last_none_below(self):
        h = md.to_html("- a\n- b\n\ntext")
        self.assertTrue(h.startswith('<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:0px;'))
        self.assertNotRegex(h, r"margin-bottom:[1-9]")

    def test_streaming_prefixes_never_fail_and_keep_earlier_blocks(self):
        text = ("Intro **bold**\n\n1. one\n2. two\n   - nested `code`\n   - more\n\n```python\nprint('x')\n```\n\n"
                "| A | B |\n|---|---|\n| 1 | 2 |\n\n> note\n\n[done](https://example.com)")
        full = md.parse(text)
        self.assertEqual([b["t"] for b in full], ["p", "list", "code", "table", "quote", "p"])
        seen = 0
        for n in range(len(text) + 1):
            h = md.to_html(text[:n])                                  # every prefix converts
            self.assertEqual(h.count("<table"), h.count("</table>"))
            self.assertEqual(h.count("<td"), h.count("</td>"))
            if "Intro" in text[:n] and n > 16:
                self.assertTrue(h.startswith('<p style="margin-top:0px; margin-bottom:0px;">Intro <b>bold</b>'), n)
            seen = max(seen, len(md.parse(text[:n])))
        self.assertGreaterEqual(seen, len(full))

    def test_a_dash_being_typed_is_not_a_heading(self):
        self.assertEqual([b["t"] for b in md.parse("Some text\n-")], ["p"])
        self.assertEqual([b["t"] for b in md.parse("Some text\n- item")], ["p", "list"])
        self.assertEqual([b["t"] for b in md.parse("Title\n---")], ["h"])

    def test_empty(self):
        self.assertEqual(md.to_html(""), "")
        self.assertEqual(md.to_html(None), "")


if __name__ == "__main__":
    unittest.main()
