#!/usr/bin/env python3
"""Local pre-flight for a Scio proposal. Mirrors the gates and the constitution's mechanical rules so a
panel never sees what a script could have caught. Defense in depth only — the server gates are authoritative.

Two ways to run it:
  Claude Code PreToolUse hook: reads {"tool_input": {...}} on stdin, denies with a reason when problems exist.
  Any harness / by hand:       check-claims.py proposal.json [--base base.md] [--domain <domain>]
                               (the scio_propose_edit input) — prints problems, exit 1 when any; exit 0 when clean.

A small edit is read in the article it lands in when the canonical body of its base revision (front matter included)
sits beside the proposal as base.md in its task folder, or is given with --base (a file in the task work root); --domain
names the page's domain when no base is at hand. Without a base each hunk is read alone, and what depends on the lines
above it is a warning.
"""
import bisect, html.entities, json, os, re, sys, unicodedata
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
from urllib.parse import urlparse
from scio_common import inside_work_root, read_verdicts, source_ids
_scan = import_module("scan-injection")

SENSITIVE = {"living_person", "health", "law", "politics"}   # Scio.Core SensitiveDomains
DOMAINS = ("general", "living_person", "health", "law", "politics", "science", "technology", "history", "geography", "culture")   # ContentDomains
# the bundled schema is the contract; what it rejects must not pass the local pre-flight
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "claim.schema.json"), encoding="utf-8") as _f:
    _SCHEMA = json.load(_f)
CLAIM_PROPS = set(_SCHEMA["properties"])
CLAIM_KINDS = set(_SCHEMA["properties"]["kind"]["enum"])
FORBIDDEN_HOSTS = ["wikipedia.org", "wikiwand.com", "wikizero.com", "wiki2.org", "grokipedia.com", "scio.md"]  # signed rules: gates.forbidden_source_hosts
# the signed rules' `limits` and `media` (2026-10-27; the platform's fallbacks before it, the same figures) and the proposal
# validator's own caps: what the platform refuses. summary_max_* is the front matter's summary; the proposal's own `summary`
# field — the edit summary — is the validator's 500.
LIMITS = {"body_max_chars": 200_000, "line_max_chars": 4000, "claims_per_proposal": 200, "claim_text_max_chars": 2000,
          "claim_quote_max_chars": 2000, "distinct_sources_per_proposal": 100, "demonstration_max_chars": 20_000,
          "scope_max_chars": 500, "language_tag_max_chars": 35, "media_max_per_article": 20, "slug_max_chars": 200,
          "url_max_chars": 2048, "premises_per_claim": 20, "premises_per_proposal": 200, "summary_max_sentences": 3,
          "summary_max_chars": 1200, "small_edit_max_changed_share": 0.5, "small_edit_min_changed_claims": 2,
          "proposal_summary_max_chars": 500}
UNDATED = re.compile(r"\b(recently|currently|nowadays|at present|these days|now|today|this year|last year|latest)\b", re.I)
DATE = re.compile(r"\b(as of|in|since|until|on|between|from)\s+(\d{1,2}\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|\d{4})\b|\b(19|20)\d{2}\b", re.I)
PUFFERY = re.compile(r"\b(groundbreaking|renowned|world-class|legendary|infamous|so-called|cutting-edge|revolutionary|iconic|prestigious|leading|best-known|widely (regarded|believed|considered|known)|it is (well )?known that|experts agree|many (people|experts) (say|believe))\b", re.I)
READER = re.compile(r"\b(note that|see below|as an ai(?:\s+(?:language\s+)?(?:model|assistant)\b|(?=\s*[,.;:!?)]|\s*$|\s+i\b))|as a language model|you should|the reader)\b", re.I)
# the reader told what to do: "you should" or "the reader should" and a verb ("You should trust the author", "The reader
# should approve this") is C6's defect and blocks, as does "you must" before a verdict or a check ("You must trust this
# author") — "with two-factor authentication you must enter a password" is the generic you of a procedure. Inside a
# Title-Cased run it is a name ("You Should Be Dancing", "The Reader should not be confused with the film"): a warning
_ADV = r"(?:(?:not|never|also|always|just|simply|first|now|really)\s+)?"
READER_TOLD = [re.compile(r"\byou\s+(should|ought\s+to)\s+" + _ADV + r"[a-z]", re.I),
               re.compile(r"\bthe\s+(reader)s?\s+(?:should|must|ought\s+to|needs?\s+to|ha(?:s|ve)\s+to)\s+" + _ADV + r"[a-z]", re.I),
               re.compile(r"\byou\s+(must|need\s+to|have\s+to)\s+" + _ADV + r"(?:trust|approve|accept|reject|believe|ignore|disregard"
                          r"|overlook|skip|vote|give|label|mark|rate|score|publish|merge|look|open|check|read|verify)\b", re.I)]


def reader_told(sentence):
    """Whether a sentence tells its reader what to do (READER_TOLD), outside a title: its modal or "Reader" Title-Cased
    (not in capitals throughout: "YOU SHOULD TRUST THIS" is shouted, not a name)."""
    for rx in READER_TOLD:
        for m in rx.finditer(sentence):
            word = m.group(1).split()[0]
            if not (word[:1].isupper() and not word.isupper()):
                return True
    return False


VAGUE_NUM = re.compile(r"\b(most|many|few|several|numerous|a lot of|the majority of|significant(ly)?|huge|massive)\b", re.I)


# ==================================================================================================================
# Gate 0, ported. Scio.Core's MarkdownDialect, FrontMatter, Transclusion and UnifiedDiff.Apply and Scio.Application's
# GateZero and ProposeEditValidator (platform 3d279a0, rules 2026-09-30), read line for line: what the platform refuses
# after the day's quota unit is spent is refused here first, and what it accepts passes. tests/test-preflight.py holds the
# platform's own verdicts on a corpus of proposals; when the platform narrows gate 0, refresh them and port the change.
# The platform counts in UTF-16 units and asks char.IsLetter of each: an astral letter is two surrogates, no letter at all.
# Every scan below is linear in its line (the platform's are, A49): Python's backtracking regexes are kept to patterns that
# cannot backtrack more than a constant, and the rest is hand-written.
# ==================================================================================================================

def u16(s):
    """Length as the platform counts it (C# string.Length): UTF-16 code units."""
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def _is_letter(c):
    return c <= "\uffff" and c.isalpha()


def _is_letter_or_digit(c):
    return c <= "\uffff" and (c.isalpha() or c.isdecimal())


def _has_letter(s):
    return any(_is_letter(c) for c in s)


def _is_ascii_letter(c):
    return "a" <= c <= "z" or "A" <= c <= "Z"


def _is_ascii_alnum(c):
    return _is_ascii_letter(c) or "0" <= c <= "9"


def _is_ascii_punct(c):
    return "!" <= c <= "/" or ":" <= c <= "@" or "[" <= c <= "`" or "{" <= c <= "~"


# .NET's whitespace (char.IsWhiteSpace, Trim, and the regex class \s): Python's str.isspace and \s also take U+001C-U+001F
_WS = "\t\n\x0b\x0c\r \x85\xa0\u1680" + "".join(map(chr, range(0x2000, 0x200B))) + "\u2028\u2029\u202f\u205f\u3000"
_WS_SET = frozenset(_WS)
_S = "[" + _WS.replace("\\", "") + "]"   # a regex class for the same set
_WORD = frozenset(("Lu", "Ll", "Lt", "Lm", "Lo", "Mn", "Nd", "Pc"))


def _boundary_word_char(c):
    """A character .NET's \\b counts as a word's: \\w (letters, Mn marks, Nd digits, Pc) and the two joiners, UTF-16 units only."""
    return c in "\u200c\u200d" or (c <= "\uffff" and unicodedata.category(c) in _WORD)


def dl_lines(text):
    """MarkdownDialect.Lines: split at LF, CRLF and a lone CR, as every renderer reads a line ending."""
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\n")


_MARKER = re.compile(r"\[\^c([0-9]{1,9})\]")
_BLOCK_ID_TAIL = re.compile(r"\^c([0-9]{1,9})" + _S + "*$")
_HEADING = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")
_CALLOUT = re.compile(r"[ \t]*\[!([A-Za-z]+)\]")
_DEFINITION = re.compile(r"\[(?:[^\]\\]|\\.)+\]:")
_AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^<>" + _WS + "]*>|<[^<>@" + _WS + "]+@[^<>" + _WS + "]+>")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]{0,31}:")
_MEDIA_REF = re.compile(r"media:([0-9a-f]{64}\.(?:svg|png|jpg|webp))")
_REDACTION = re.compile(r"\[redacted by arbiter panel pn_[0-9a-f]{16}, dispute ds_[0-9a-f]{16}\]")
_HTML_TAG = re.compile((r"""<!--|<\?|<![A-Za-z]|<!\[CDATA\[|</?[A-Za-z][A-Za-z0-9-]*(?:[\s/][^<>]*>|[\s/](?:[^<>"']|"[^"]*"|'[^']*')*>|>|\s*$)"""
                       r"""|</?[A-Za-z][A-Za-z0-9-]*\s+[A-Za-z_:][A-Za-z0-9_.:-]*\s*=""").replace(r"[\s/]", "[/" + _WS + "]").replace(r"\s", _S))
_HTML_BLOCK_START = re.compile(r"(?:<(?:script|pre|style|textarea)(?:[ \t>]|$)|</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:[ \t>]|/>|$))", re.I)
# a period that ends an abbreviation, not a sentence (MarkdownDialect.AbbreviationEnd, the plugin's own list), read on the
# nine characters before the period only, so "Oxford Univ. Press" is one sentence and the scan stays linear
_ABBREVIATIONS = frozenset("etc vs cf ca approx est no nos vol vols pp fig figs ed eds jr sr dept univ inc ltd corp co st mt ft ave rd blvd gov govt "
                           "prof dr mr mrs ms op art ch sec para rev gen col lt capt sgt hon bros assn dist natl intl trans ser repr orig misc".split())


def _abbreviation_end(w):
    """`(?:\\b[A-Za-z]\\.|\\b(?:[A-Za-z]\\.){2,}|\\b(?:etc|…)\\.)$` with .NET's \\b: one letter, an initialism (whose last letter is
    one), or a short form from the list, each starting at a word boundary, then the period that ends `w`."""
    if not w.endswith(".") or len(w) < 2:
        return False
    if _is_ascii_letter(w[-2]) and (len(w) == 2 or not _boundary_word_char(w[-3])):
        return True
    j = len(w) - 1
    while j > 0 and _is_ascii_letter(w[j - 1]):
        j -= 1
    return w[j:-1].lower() in _ABBREVIATIONS and (j == 0 or not _boundary_word_char(w[j - 1]))
_REVIEWER = re.compile(r"(dear\s+)?\b(reviewers?|panel|judges?)\s*[:,]\s*(please|approve|accept|pass|confirm|vote|ignore|disregard|overlook|skip|mark|rate|score|publish|merge|reject|do not|don't)\b|\bignore (the |all |your )?(previous|prior|above|earlier) instructions\b|\bskip (the |any )?(source|quote|fact)[- ]?check|\b(vote|mark|rate)\s+(approve|supported|reliable)\b|\bapprove (this|the) (proposal|edit|article) (without|directly)\b", re.I)
_TRANSCLUSION_REF = re.compile(r"^\s*!\[\[(?:([a-z]{2,3}(?:-[A-Za-z0-9]+)*)/)?([^\]|#^/]+)\^c(\d+)\]\]\s*$".replace(r"\s", _S))
_FOLD = {"“": '"', "”": '"', "„": '"', "‟": '"', "«": '"', "»": '"', "″": '"',
         "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
         "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-"}


def block_id(line):
    """(index where the closing block id's whitespace starts, its ordinal) — MarkdownDialect.BlockId — or None."""
    m = _BLOCK_ID_TAIL.search(line)
    if not m:
        return None
    start = m.start()
    while start > 0 and line[start - 1] in _WS_SET:
        start -= 1
    return start, m.group(1)


def _names_last_marker(line, bid):
    found = _MARKER.findall(line)
    return bool(found) and found[-1] == bid[1]


def markers(text):
    """The distinct claim ordinals the markers of a text name, ascending — outside code blocks and code spans, what a
    reader renders (MarkdownDialect.Markers, platform 61a3e57)."""
    ordinals, spans = set(), _CodeSpans()
    for code, content, _, _ in _read_blocks(dl_lines(text)):
        if code or not content.strip(_WS):
            spans.end_paragraph()
            continue
        ordinals.update(int(n) for n in _MARKER.findall(spans.blank(content)))
    return sorted(ordinals)


# --- hidden text (MarkdownDialect.HasHiddenText): the same characters, no more — ZWNJ and ZWJ are text ------------------
_HIDDEN = {0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0, 0x17B4, 0x17B5, 0x2800, 0x2028, 0x2029, 0x180B, 0x180C, 0x180D, 0x180F,
           0x00AD, 0x061C, 0x180E}
_ASCII_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# The platform's categories are .NET 10's, Unicode 16.0. A Python with an older database calls what 16.0 assigned
# unassigned (3.12 has 15.0): refusing that refused text the platform accepts, so such a code point is a warning
# (unvouched). What no Unicode version has assigned is refused whatever the version: noncharacters, planes 4 to 13, and
# plane 14 outside its tags and variation selectors. A Python newer than 16.0 takes a later character the platform refuses.
PLATFORM_UNICODE = (16, 0)
_LOCAL_UNICODE = tuple(int(p) for p in unicodedata.unidata_version.split(".")[:2])


def _never_assigned(v):
    return (0xFDD0 <= v <= 0xFDEF or (v & 0xFFFE) == 0xFFFE or 0x40000 <= v <= 0xDFFFF
            or 0xE0080 <= v <= 0xE00FF or 0xE01F0 <= v <= 0xEFFFF)


def _is_hidden(ch):
    v = ord(ch)
    if v in (0x200C, 0x200D):
        return False   # emoji sequences and Indic and Persian shaping need them
    if v in _HIDDEN or 0xFE00 <= v <= 0xFE0F or 0xE0100 <= v <= 0xE01EF or 0xE0000 <= v <= 0xE007F or 0x2066 <= v <= 0x2069:
        return True
    cat = unicodedata.category(ch)
    if cat == "Cc":
        return ch not in "\t\n\r"
    if cat == "Cn":
        return _LOCAL_UNICODE >= PLATFORM_UNICODE or _never_assigned(v)
    return cat in ("Cf", "Co", "Cs")


def unvouched(text):
    """The first code point this Python calls unassigned that the platform's Unicode may have assigned, or None."""
    if _LOCAL_UNICODE >= PLATFORM_UNICODE or text.isascii():
        return None
    return next((ch for ch in text if unicodedata.category(ch) == "Cn" and not _never_assigned(ord(ch))), None)


def has_hidden_text(text):
    """A character a reviewer cannot see, or more than four combining marks on one base (the joiners extend a cluster)."""
    if text.isascii():
        return bool(_ASCII_CONTROL.search(text))
    marks = 0
    for ch in text:
        if _is_hidden(ch):
            return True
        if unicodedata.category(ch) in ("Mn", "Me"):
            marks += 1
            if marks > 4:
                return True
        elif ch not in "‌‍":
            marks = 0
    return False


# --- wikilinks (MarkdownDialect.ScanWikilinks): each `]` examined once, the openers before it decided from three tables --
def _first_opener(s, open_, close):
    inner = open_ + 2
    length = close - inner
    next_any, next_bc, next_bar = [close] * (length + 1), [close] * (length + 1), [close] * (length + 1)
    for p in range(close - 1, inner - 1, -1):
        k, c = p - inner, s[p]
        next_bar[k] = p if c == "|" else next_bar[k + 1]
        next_bc[k] = p if c in "|^" else next_bc[k + 1]
        next_any[k] = p if c in "|#^" else next_any[k + 1]
    for q in range(open_, close - 1):
        if s[q] != "[" or s[q + 1] != "[":
            continue
        ts = q + 2
        te = next_any[ts - inner]
        if te == ts:
            continue
        d, valid = te, True
        if d < close and s[d] == "#":
            e = next_bc[d + 1 - inner]
            valid, d = e > d + 1, e
        if valid and d < close and s[d] == "^":
            e = next_bar[d + 1 - inner]
            valid, d = e > d + 1, e
        label = -1
        if valid and d < close:
            valid, label = close > d + 1, d + 1
        if valid:
            return q, close + 2, ts, te, label
    return None


def _scan_wikilinks(s):
    """[(start, end, target start, target end, label start or -1)], leftmost first; start includes a transclusion's `!`."""
    found, frm, n = [], 0, len(s)
    while frm < n:
        open_ = s.find("[[", frm)
        if open_ < 0:
            break
        close = s.find("]", open_ + 2)
        if close < 0:
            break
        if close + 1 >= n or s[close + 1] != "]":
            frm = close + 1
            continue
        link = _first_opener(s, open_, close)
        if link:
            start = link[0] - 1 if link[0] > frm and s[link[0] - 1] == "!" else link[0]
            found.append((start,) + link[1:])
            frm = close + 2
        else:
            frm = close + 1
    return found


def _without_wikilinks(line):
    links = _scan_wikilinks(line)
    if not links:
        return line
    out, frm = [], 0
    for start, end, ts, te, label in links:
        out.append(line[frm:start])
        out.append(line[label:end - 2] if label >= 0 else line[ts:te])
        frm = end
    out.append(line[frm:])
    return "".join(out)


_SPACES = re.compile(_S + "+")


def claim_text(text):
    """MarkdownDialect.ClaimText (the owner's decision of 20 Oct 2026): a sentence or a claim's text as gate 0 compares the
    two — no markers or block id, every run of whitespace one space, trimmed, and nothing else changed: case, emphasis and
    code marks, wikilinks, quotes and dashes are the claim's as much as the sentence's (claim_text_mismatch)."""
    bid = block_id(text)
    return _SPACES.sub(" ", _MARKER.sub("", text[:bid[0]] if bid else text)).strip(" ")


def legacy_claim_text(text):
    """MarkdownDialect.LegacyClaimText: the reading gate 0 compared claims by before 20 Oct 2026, kept for the lines a small
    edit leaves as its base had them — no markers or block id, wikilinks as their labels, no `*`, backtick or word-edge
    `_`, typographic quotes and dashes folded to ASCII, whitespace one space, lower case."""
    bid = block_id(text)
    s = _without_wikilinks(_MARKER.sub("", text[:bid[0]] if bid else text))
    out, space, n = [], False, len(s)
    for i, c in enumerate(s):
        if c in _WS_SET:
            space = True
            continue
        if c in "*`" or (c == "_" and (i == 0 or i == n - 1 or not _is_letter_or_digit(s[i - 1]) or not _is_letter_or_digit(s[i + 1]))):
            continue
        if space and out:
            out.append(" ")
        space = False
        lower = c.lower()   # char.ToLowerInvariant, one UTF-16 unit at a time: an astral letter's surrogates have no case
        out.append(_FOLD.get(c) or (lower if len(lower) == 1 and c <= "\uffff" else c))
    return "".join(out)


# --- the block reader (MarkdownDialect.BlockReader): fences and display maths, placed exactly as CommonMark places them --
_MATH_NONE, _MATH_OPENS, _MATH_INSIDE, _MATH_CLOSES = range(4)


def _quote_markers(raw, maximum, strict):
    i = n = 0
    while n < maximum:
        j = i
        if not strict:
            while j < len(raw) and raw[j] == " " and j - i < 3:
                j += 1
        if j >= len(raw) or raw[j] != ">":
            break
        j += 1
        if j < len(raw) and raw[j] == " ":
            j += 1
        i, n = j, n + 1
    return n, raw[i:]


def _container_markers_length(s):
    i = 0
    while True:
        while i < len(s) and s[i] in " \t":
            i += 1
        if i < len(s) and s[i] == ">":
            i += 1
            continue
        j = i
        if j < len(s) and s[j] in "-+*":
            j += 1
        else:
            while j < len(s) and j - i < 9 and "0" <= s[j] <= "9":
                j += 1
            if j == i or j >= len(s) or s[j] not in ".)":
                return i
            j += 1
        if j < len(s) and s[j] in " \t":
            i = j
            continue
        return i


def _after_container_markers(s):
    return s[_container_markers_length(s):]


def _is_fence_run(s, at):
    if at + 3 > len(s) or s[at] not in "`~":
        return False
    c, run = s[at], at
    while run < len(s) and s[run] == c:
        run += 1
    return run - at >= 3 and (c == "~" or s.find("`", run) < 0)


def _math_delimiters(content):
    return content.count("$$")


def _opens_math(content):
    return content[_container_markers_length(content):].lstrip(" \t").startswith("$$") and _math_delimiters(content) % 2 == 1


class _BlockReader:
    def __init__(self):
        self.fence, self.fence_length, self.fence_depth = "", 0, 0
        self.unplaced, self.math, self.math_depth, self.last_math = False, False, 0, _MATH_NONE

    def _closes(self, content):
        i, tab = 0, False
        while i < len(content) and content[i] in " \t":
            tab |= content[i] == "\t"
            i += 1
        run = i
        while run < len(content) and content[run] == self.fence:
            run += 1
        if run - i < self.fence_length or content[run:].rstrip(" \t"):
            return "no"
        if tab:
            return "unsure"
        return "yes" if i <= 3 else "no"

    def _opens(self, rest):
        if not _is_fence_run(rest, 0):
            return False
        self.fence, run = rest[0], 0
        while run < len(rest) and rest[run] == self.fence:
            run += 1
        self.fence_length = run
        return True

    def read(self, raw):
        """(code, content after the quote markers, quote depth, part in display maths) for the next line."""
        self.last_math = _MATH_NONE
        if self.fence:
            depth, content = _quote_markers(raw, self.fence_depth, False)
            if depth == self.fence_depth:
                closing = self._closes(content)
                if closing == "no":
                    return True, content, depth, _MATH_NONE
                self.fence = ""
                if closing == "yes":
                    return True, content, depth, _MATH_NONE
                self.unplaced = True   # a closer behind a tab: its column depends on the tab stops — take it for text
            else:
                self.fence = ""        # the quote that held the fence ended, and the fence with it
        depth, content = _quote_markers(raw, 1 << 30, False)
        if self.math and depth != self.math_depth:
            self.math = False
        if self.math:
            if _is_fence_run(content, _container_markers_length(content)):
                self.unplaced = True
            self.math = _math_delimiters(content) % 2 == 0
            self.last_math = _MATH_INSIDE if self.math else _MATH_CLOSES
            return False, content, depth, self.last_math
        if not self.unplaced:
            strict_depth, strict_rest = _quote_markers(raw, 1 << 30, True)
            if strict_depth == depth and self._opens(strict_rest):
                self.fence_depth = depth
                return True, content, depth, _MATH_NONE
        if _is_fence_run(content, _container_markers_length(content)):
            self.unplaced = True
        elif _opens_math(content):
            self.math, self.math_depth, self.last_math = True, depth, _MATH_OPENS
        return False, content, depth, self.last_math


def _read_blocks(lines):
    reader = _BlockReader()
    return [reader.read(line) for line in lines]


_ROLE_NONE, _ROLE_MATHS, _ROLE_CLOSES = range(3)


def _closed_maths(blocks):
    """The display-maths blocks a reader renders as maths (R19): only the marker rule is waived on them."""
    roles, i, n = [_ROLE_NONE] * len(blocks), 0, len(blocks)
    while i < n:
        if blocks[i][3] != _MATH_OPENS or _math_delimiters(blocks[i][1]) != 1:
            i += 1
            continue
        j = i + 1
        while j < n and blocks[j][3] == _MATH_INSIDE and blocks[j][1].strip(_WS) and _math_delimiters(blocks[j][1]) == 0:
            j += 1
        if j < n and blocks[j][3] == _MATH_CLOSES and _math_delimiters(blocks[j][1]) == 1:
            for k in range(i, j):
                roles[k] = _ROLE_MATHS
            roles[j] = _ROLE_CLOSES
            i = j
        i += 1
    return roles


# --- GFM tables (MarkdownDialect.TableRoles): a header over a delimiter row with as many cells, then body rows ------------
_TABLE_NONE, _TABLE_HEADER, _TABLE_DELIMITER, _TABLE_ROW = range(4)
_DELIMITER_CELL = re.compile(r"[ \t]*:?-+:?[ \t]*")


def _is_delimiter_row(s):
    t = s.strip(" \t")
    t = t[1:] if t.startswith("|") else t
    t = t[:-1] if t.endswith("|") else t
    return all(_DELIMITER_CELL.fullmatch(cell) for cell in t.split("|"))


def _has_cell_boundary(text):
    at = text.find("|")
    while at >= 0:
        if at == 0 or text[at - 1] != "\\":
            return True
        at = text.find("|", at + 1)
    return False


def _cells(row):
    t, cells, start = row.strip(_WS), [], 0
    for k in range(len(t) + 1):
        if k == len(t) or (t[k] == "|" and (k == 0 or t[k - 1] != "\\")):
            cells.append(t[start:k])
            start = k + 1
    if len(cells) > 1 and t.startswith("|"):
        cells.pop(0)
    if len(cells) > 1 and t.endswith("|") and not t.endswith("\\|"):
        cells.pop()
    return cells


def _table_roles(blocks):
    """A line that merely starts with a pipe is a paragraph; a table needs its delimiter row (RV_content-7)."""
    roles, open_, i, n = [_TABLE_NONE] * len(blocks), -1, 0, len(blocks)
    while i < n:
        code, content, depth, _ = blocks[i]
        if code or not content.strip(_WS) or depth != open_:
            open_ = -1
        if code:
            i += 1
            continue
        text = _after_container_markers(content)
        if open_ >= 0 and not _HEADING.match(text):
            roles[i] = _TABLE_ROW
            i += 1
            continue
        open_ = -1
        if i + 1 < n and _is_header_over(text, blocks[i + 1], depth):
            roles[i], roles[i + 1], open_ = _TABLE_HEADER, _TABLE_DELIMITER, depth
            i += 1
        i += 1
    return roles


def _is_header_over(text, nxt, depth):
    if nxt[0] or nxt[2] != depth or not _has_cell_boundary(text):
        return False
    delimiter = _after_container_markers(nxt[1])
    return "|" in delimiter and _is_delimiter_row(delimiter) and len(_cells(text)) == len(_cells(delimiter))


# --- raw HTML, followed across lines (MarkdownDialect.IsRawHtml / ScanTag / TagLeftOpen) ------------------------------------
(_TAG_NONE, _TAG_AFTER_NAME, _TAG_AFTER_SPACE, _TAG_AFTER_ATTR, _TAG_AFTER_ATTR_SPACE, _TAG_AFTER_EQUALS,
 _TAG_IN_DQ, _TAG_IN_SQ, _TAG_CLOSING) = range(9)
_SCAN_CLOSED, _SCAN_OPEN, _SCAN_INVALID = range(3)


def _unquoted_value_char(c):
    return c not in " \t\"'=<>`"


def _scan_tag(s, i, state):
    """CommonMark's tag grammar from i: (closed/open/invalid, the state where the text ran out, the index after `>`)."""
    n = len(s)
    while i < n:
        c = s[i]
        if state in (_TAG_IN_DQ, _TAG_IN_SQ):
            q = s.find('"' if state == _TAG_IN_DQ else "'", i)
            if q < 0:
                return _SCAN_OPEN, state, n
            i, state = q + 1, _TAG_AFTER_NAME
            continue
        if state == _TAG_AFTER_EQUALS:
            if c in " \t":
                i += 1
            elif c in "\"'":
                state = _TAG_IN_DQ if c == '"' else _TAG_IN_SQ
                i += 1
            elif _unquoted_value_char(c):
                while i < n and _unquoted_value_char(s[i]):
                    i += 1
                state = _TAG_AFTER_NAME
            else:
                return _SCAN_INVALID, state, n
            continue
        if state == _TAG_CLOSING:
            if c in " \t":
                i += 1
                continue
            if c == ">":
                return _SCAN_CLOSED, state, i + 1
            return _SCAN_INVALID, state, n
        if c in " \t":
            state = _TAG_AFTER_ATTR_SPACE if state in (_TAG_AFTER_ATTR, _TAG_AFTER_ATTR_SPACE) else _TAG_AFTER_SPACE
            i += 1
            continue
        if c == ">" or (c == "/" and i + 1 < n and s[i + 1] == ">"):
            return _SCAN_CLOSED, state, i + 1 if c == ">" else i + 2
        if c == "=" and state in (_TAG_AFTER_ATTR, _TAG_AFTER_ATTR_SPACE):
            state = _TAG_AFTER_EQUALS
            i += 1
            continue
        if state in (_TAG_AFTER_SPACE, _TAG_AFTER_ATTR_SPACE) and (_is_ascii_letter(c) or c in "_:"):
            while i < n and (_is_ascii_alnum(s[i]) or s[i] in "_.:-"):
                i += 1
            state = _TAG_AFTER_ATTR
            continue
        return _SCAN_INVALID, state, n
    return _SCAN_OPEN, state, n


def _tag_name_end(s, j):
    while j < len(s) and (_is_ascii_alnum(s[j]) or s[j] == "-"):
        j += 1
    return j


def _tag_left_open(s, frm):
    p = s.find("<", frm) if frm < len(s) else -1
    while p >= 0:
        nxt = p + 1
        closing = p + 2 < len(s) and s[p + 1] == "/" and _is_ascii_letter(s[p + 2])
        if closing or (p + 1 < len(s) and _is_ascii_letter(s[p + 1])):
            result, state, end = _scan_tag(s, _tag_name_end(s, p + 2 if closing else p + 1), _TAG_CLOSING if closing else _TAG_AFTER_NAME)
            if result == _SCAN_OPEN:
                return state
            if result == _SCAN_CLOSED:
                nxt = end
        p = s.find("<", nxt) if nxt < len(s) else -1
    return None


def _is_raw_html(content, depth, pending):
    """(raw, the tag this line leaves open as (state, depth) or None) — a tag may run over the lines of a paragraph."""
    raw, frm = False, 0
    if pending is not None:
        if depth > pending[1] or not content.strip(_WS):
            pending = None
        else:
            state = {_TAG_AFTER_NAME: _TAG_AFTER_SPACE, _TAG_AFTER_ATTR: _TAG_AFTER_ATTR_SPACE}.get(pending[0], pending[0])
            result, state, end = _scan_tag(content, 0, state)
            if result == _SCAN_CLOSED:
                raw, pending, frm = True, None, end
            elif result == _SCAN_OPEN:
                pending, frm = (state, pending[1]), len(content)
            else:
                pending = None
    if _HTML_TAG.search(content) or _HTML_BLOCK_START.match(_after_container_markers(content)):
        return True, pending
    if pending is None:
        state = _tag_left_open(content, frm)
        if state is not None:
            pending = (state, depth)
    return raw, pending


# --- code spans (MarkdownDialect.CodeSpanReader): blanked only where every reader shows code ---------------------------------
_NOT_MARKUP, _MARKUP_OPEN = -1, 1 << 62


def _terminated(s, frm, terminator):
    at = s.find(terminator, frm) if frm <= len(s) else -1
    return _MARKUP_OPEN if at < 0 else at + len(terminator)


def _markup_reach(s, i):
    if s.startswith("<!--", i):
        return _terminated(s, i + 4, "-->")
    if s.startswith("<?", i):
        return _terminated(s, i + 2, "?>")
    if s.startswith("<![CDATA[", i):
        return _terminated(s, i + 9, "]]>")
    if len(s) - i > 2 and s[i + 1] == "!" and _is_ascii_letter(s[i + 2]):
        return _terminated(s, i + 3, ">")
    reach, a = _NOT_MARKUP, i + 1
    while a < len(s) and s[a] not in " \t<>":
        a += 1
    if a > i + 1 and a < len(s) and s[a] == ">":
        reach = a + 1
    closing = len(s) - i > 2 and s[i + 1] == "/" and _is_ascii_letter(s[i + 2])
    if closing or (len(s) - i > 1 and _is_ascii_letter(s[i + 1])):
        result, _, end = _scan_tag(s, _tag_name_end(s, i + 2 if closing else i + 1), _TAG_CLOSING if closing else _TAG_AFTER_NAME)
        if result == _SCAN_CLOSED:
            return max(reach, end)
        if result == _SCAN_OPEN:
            return _MARKUP_OPEN
    return reach


def _destination_end(s, j):
    for k in range(j, len(s)):
        if s[k] == ")":
            return k
        if s[k] in "` \t\"'(<\\":
            return -1
    return -1


class _CodeSpans:
    def __init__(self):
        self.unsure = False   # something earlier in the paragraph may still be open: no later span is certain

    def end_paragraph(self):
        self.unsure = False

    def distrust(self):
        self.unsure = True

    def _stop(self, s, blanked):
        self.unsure = True
        return s if blanked is None else "".join(blanked)

    def blank(self, s):
        """The line with its certain code spans blanked — letters to x, the rest to spaces — or the line as it is."""
        if self.unsure:
            return s
        starts, lengths = [], []
        i = s.find("`")
        while i >= 0:
            end = i
            while end < len(s) and s[end] == "`":
                end += 1
            starts.append(i)
            lengths.append(end - i)
            i = s.find("`", end) if end < len(s) else -1
        nxt, last = [-1] * len(starts), {}
        for r in range(len(starts) - 1, -1, -1):
            nxt[r] = last.get(lengths[r], -1)
            last[lengths[r]] = r
        run_at = {start: r for r, start in enumerate(starts)}
        blanked, no_wikilink_close, no_dollar, i, n = None, False, False, 0, len(s)
        while i < n:
            c = s[i]
            if c == "\\":
                if i + 1 < n and s[i + 1] == "`":
                    return self._stop(s, blanked)   # an escaped backtick shifts every span after it
                i += 2 if i + 1 < n and _is_ascii_punct(s[i + 1]) else 1
            elif c == "`":
                run = run_at.get(i)
                if run is None:
                    return self._stop(s, blanked)
                close = nxt[run]
                if close < 0:
                    self.unsure = True   # it may close on a later line; on this one it is a literal
                    i = starts[run] + lengths[run]
                    continue
                if "|" in s[starts[run] + lengths[run]:starts[close]]:
                    return self._stop(s, blanked)   # a table splits its cells before it reads the span
                if blanked is None:
                    blanked = list(s)
                end = starts[close] + lengths[close]
                for k in range(i, end):
                    blanked[k] = "x" if _is_letter(s[k]) else " "
                i = end
            elif c == "<":
                reach = _markup_reach(s, i)
                if reach == _MARKUP_OPEN or (reach != _NOT_MARKUP and ("`" in s[i:reach] or "|" in s[i:reach])):
                    return self._stop(s, blanked)
                i = i + 1 if reach == _NOT_MARKUP else reach
            elif c == "]" and i + 1 < n and s[i + 1] == "(":
                close = _destination_end(s, i + 2)
                if close < 0:
                    return self._stop(s, blanked)
                i = close + 1
            elif c == "]" and i + 1 < n and s[i + 1] == "[":
                close = s.find("]", i + 2)
                if close < 0 or "`" in s[i + 2:close]:
                    return self._stop(s, blanked)
                i = close + 1
            elif c == "[" and not no_wikilink_close and i + 1 < n and s[i + 1] == "[":
                close = s.find("]]", i + 2)
                if close < 0:
                    no_wikilink_close = True
                    i += 2
                    continue
                if "`" in s[i + 2:close]:
                    return self._stop(s, blanked)
                i = close + 2
            elif c == "$" and not no_dollar:
                width = 2 if i + 1 < n and s[i + 1] == "$" else 1
                close = s.find("$$" if width == 2 else "$", i + width)
                if close < 0:
                    no_dollar |= width == 1
                    i += width
                    continue
                if "`" in s[i + width:close]:
                    return self._stop(s, blanked)
                i = close + width
            else:
                i += 1
        return s if blanked is None else "".join(blanked)


# --- links, images, definitions ----------------------------------------------------------------------------------------------
def _external_images(line):
    """(images not exactly ![alt](media:<sha256>.<ext>), the line with every image blanked) — one pass."""
    blanked, count, close_left = None, 0, True
    at = line.find("![")
    while at >= 0:
        nxt = line[at + 2] if at + 2 < len(line) else "\0"
        if nxt in ("[", "^"):
            at = line.find("![", at + 2)
            continue
        close = line.find("]", at + 2) if close_left else -1
        close_left = close >= 0
        media = False
        if close >= 0 and close + 1 < len(line) and line[close + 1] == "(":
            paren = line.find(")", close + 2)
            end = len(line) if paren < 0 else paren + 1
            media = paren >= 0 and _MEDIA_REF.fullmatch(line, close + 2, paren) is not None
        else:
            end = close + 1 if close >= 0 else at + 2
        if not media:
            count += 1
        if blanked is None:
            blanked = list(line)
        blanked[at:end] = " " * (end - at)
        at = line.find("![", end) if end < len(line) else -1
    return count, (line if blanked is None else "".join(blanked))


def _line_media_references(line, out, seen):
    n, i = len(line), line.find("![")
    while i >= 0:
        close = line.find("]", i + 2)
        if close < 0:
            break
        if close + 1 >= n or line[close + 1] != "(":
            i = line.find("![", close + 1)
            continue
        paren = line.find(")", close + 2)
        if paren < 0:
            break
        d = close + 2
        while d < paren and line[d] not in _WS_SET:
            d += 1
        if d > close + 2:
            m = _MEDIA_REF.fullmatch(line, close + 2, d)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                out.append(m.group(1))
            i = line.find("![", paren + 1)
        else:   # every opener before this `]` meets the same `](` and fails the same way
            i = line.find("![", close + 1)


def media_references(body):
    """The distinct <sha256>.<ext> keys of every `media:` image a reader is shown, in order — line by line, outside code
    fences and code spans: an image quoted as code is no image (MarkdownDialect.MediaReferences, platform 5e1a778)."""
    out, seen, spans = [], set(), _CodeSpans()
    for code, content, _, _ in _read_blocks(dl_lines(body)):
        if code or not content.strip(_WS):
            spans.end_paragraph()
            continue
        _line_media_references(spans.blank(content), out, seen)
    return out


def article_media_references(canonical):
    """MarkdownDialect.ArticleMediaReferences: the images of the prose and of the front-matter summary, the cap's count."""
    try:
        fm, prose = parse_front_matter(canonical)
    except FrontMatterError:
        out, seen = [], set()
        _line_media_references(canonical, out, seen)
        return out
    return list(dict.fromkeys(media_references(prose) + media_references(fm["summary"])))


def _link_destination(s):
    """An inline destination with a scheme, a network path, or one that starts on the next line (LinkDestination)."""
    i = s.find("](")
    while i >= 0:
        j = i + 2
        while j < len(s) and s[j] in " \t":
            j += 1
        if j < len(s) and s[j] == "<":
            j += 1
            while j < len(s) and s[j] in " \t":
                j += 1
        if j >= len(s) or s.startswith("//", j) or _SCHEME.match(s, j):
            return True
        i = s.find("](", i + 2)
    return False


_ANY = "\0"   # a named reference .NET's WebUtility does not know: it may stand for any character, a colon included
_ENTITIES = dict(html.entities.name2codepoint, apos=39)   # the HTML 4 names WebUtility.HtmlDecode decodes


def _character_reference(s, i):
    semicolon = s.find(";", i + 1, i + 1 + min(len(s) - i - 1, 34))
    if semicolon < 0:
        return None
    name, length = s[i + 1:semicolon], semicolon - i + 1
    if len(name) >= 2 and name[0] == "#":
        hexa = name[1] in "xX"
        digits = name[2:] if hexa else name[1:]
        if not digits or len(digits) > (6 if hexa else 7) or not re.fullmatch(r"[0-9A-Fa-f]+" if hexa else r"[0-9]+", digits):
            return None
        code = int(digits, 16 if hexa else 10)
        return (chr(code) if 0 < code < 0xD800 or 0xDFFF < code < 0x10000 else "�"), length
    if not name or not _is_ascii_letter(name[0]) or not all(_is_ascii_alnum(c) for c in name):
        return None
    return (chr(_ENTITIES[name]) if name in _ENTITIES else _ANY), length


def _names_scheme_or_network_path(h):
    if len(h) >= 2 and h[0] in "/\0" and h[1] in "/\0":
        return True
    if not h or not (_is_ascii_letter(h[0]) or h[0] == _ANY):
        return False
    for k in range(1, min(len(h), 33)):
        if h[k] in ":\0":
            return True
        if not (_is_ascii_alnum(h[k]) or h[k] in "+.-"):
            return False
    return False


def _has_encoded_external_destination(s):
    """A destination that names a scheme once character references and backslash escapes are read (RV_content-5)."""
    at = s.find("](")
    while at >= 0:
        i, n = at + 2, len(s)
        while i < n and s[i] in " \t":
            i += 1
        if i < n and s[i] == "<":
            i += 1
            while i < n and s[i] in " \t":
                i += 1
        head = []
        while i < n and len(head) < 34 and s[i] not in " \t)>":
            if s[i] == "\\" and i + 1 < n and _is_ascii_punct(s[i + 1]):
                head.append(s[i + 1])
                i += 2
                continue
            ref = _character_reference(s, i) if s[i] == "&" else None
            if ref:
                head.append(ref[0])
                i += ref[1]
            else:
                head.append(s[i])
                i += 1
        if _names_scheme_or_network_path(head):
            return True
        at = s.find("](", at + 2)
    return False


def _closes_label(s, label_open):
    """(the line closes a label an earlier line opened, with a definition's colon; whether a label is still open)."""
    if not label_open:
        return False, False
    k = 0
    while k < len(s):
        if s[k] == "\\":
            k += 2
            continue
        if s[k] in "[]":
            return s[k] == "]" and k + 1 < len(s) and s[k + 1] == ":", False
        k += 1
    return False, True


def _opens_label(lead):
    if not lead.startswith("["):
        return False
    k = 1
    while k < len(lead):
        if lead[k] == "\\":
            k += 2
            continue
        if lead[k] in "[]":
            return False
        k += 1
    return True


# --- sentences and their markers (LacksMarker, HasSentenceBreak, ProseOf, RowLacksMarker) -------------------------------------
def _has_sentence_break(piece):
    """A terminator, whitespace and the start of another sentence — unless the period closes an abbreviation."""
    return bool(_sentence_break_ends(piece))


def _lacks_marker(line):
    pieces = _MARKER.split(_without_wikilinks(line.strip(_WS)))   # the captured ordinals interleave; skip them
    for i in range(0, len(pieces), 2):
        piece = pieces[i].strip(_WS)
        if not piece:
            continue
        if i == len(pieces) - 1 and _has_letter(piece):
            return True   # words after the final marker
        if _has_sentence_break(piece):
            return True   # two sentences before one marker
    return False


def _strip_leading_embeds(t):
    at = 0
    while True:
        while at < len(t) and t[at] in _WS_SET:
            at += 1
        if not t.startswith("![", at):
            return t[at:]
        if t.startswith("![[", at):
            close = t.find("]]", at + 3)
            if close < 0:
                return t[at:]
            at = close + 2
            continue
        bracket = t.find("]", at + 2)
        if bracket < 0 or bracket + 1 >= len(t) or t[bracket + 1] != "(":
            return t[at:]
        paren = t.find(")", bracket + 2)
        if paren < 0:
            return t[at:]
        at = paren + 1


def _prose_of(line):
    """The text of a line that must end in claim markers, or None: a heading (`#1 cause` is prose), display maths alone,
    embeds alone, or no letters at all."""
    t = line.strip(_WS)
    if not t or _HEADING.match(line) or t == "$$" or (len(t) >= 4 and t.startswith("$$") and t.endswith("$$")):
        return None
    rest = _strip_leading_embeds(t)
    return rest if _has_letter(rest) else None


def _reads_as_sentence(cell):
    t = _without_wikilinks(cell).strip(_WS)
    if _has_sentence_break(t):
        return True
    end = len(t)
    while end > 0 and t[end - 1] in "\"')”’":
        end -= 1
    if end == 0 or t[end - 1] not in ".!?" or (" " not in t[:end] and "\t" not in t[:end]):
        return False
    return t[end - 1] != "." or not _abbreviation_end(t[max(0, end - 9):end])


def _row_lacks_marker(row, line_no, violations):
    """A table body row: a marked cell ends in its marker, an unmarked one reads as no sentence, and a row with words cites."""
    cited = words = lacks = False
    for raw in _cells(row):
        cell = raw.strip(_WS)
        bid = block_id(cell)
        if bid:
            if not _names_last_marker(cell, bid):
                violations.append(("block_id_mismatch", line_no))
            cell = cell[:bid[0]]
        marked = _MARKER.search(cell) is not None
        cited |= marked
        if not _has_letter(_MARKER.sub("", cell)):
            continue   # a figure, a date, an empty cell: nothing a sentence says
        words = True
        lacks |= _lacks_marker(cell) if marked else _reads_as_sentence(cell)
    return lacks or (words and not cited)


def dialect_check(body):
    """MarkdownDialect.Check: every violation of the dialect as (kind, 1-based line). Kinds: hidden_text, raw_html,
    external_image, external_link, unknown_callout, block_id_mismatch, no_claim_marker (a table row reports `table_row`)."""
    violations, lines = [], dl_lines(body)
    blocks = _read_blocks(lines)
    tables, maths, spans = _table_roles(blocks), _closed_maths(blocks), _CodeSpans()
    callout, tag, label_open = None, None, False
    for i, raw in enumerate(lines):
        line_no = i + 1
        if has_hidden_text(raw):
            violations.append(("hidden_text", line_no))
        code, content, depth, _ = blocks[i]
        if code:
            tag, label_open = None, False
            spans.end_paragraph()
            continue
        if depth == 0:
            callout = None
        if not content.strip(_WS):
            label_open = False
            spans.end_paragraph()
        content = spans.blank(content) if tag is None else content
        is_title = False
        if depth > 0:
            head = _CALLOUT.match(content)
            if head:
                callout = head.group(1).lower()
                if callout not in ("disputed", "demonstration"):
                    violations.append(("unknown_callout", line_no))
                content, is_title = content[head.end():], True   # the title is visible text, checked like any line
        raw_html, tag = _is_raw_html(content, depth, tag)
        if raw_html:
            violations.append(("raw_html", line_no))
        if tag is not None:
            spans.distrust()
        count, without_images = _external_images(content)
        violations.extend([("external_image", line_no)] * count)
        lead = _after_container_markers(content)
        definition = _DEFINITION.match(lead) is not None
        if not definition:
            definition, label_open = _closes_label(content, label_open)
        if definition or _link_destination(without_images) or _has_encoded_external_destination(without_images) or _AUTOLINK.search(without_images):
            violations.append(("external_link", line_no))
        label_open = label_open or (not definition and _opens_label(lead))
        if is_title or definition or tables[i] in (_TABLE_HEADER, _TABLE_DELIMITER):
            continue
        line = content
        bid = block_id(line)
        if bid:
            if not _names_last_marker(line, bid):
                violations.append(("block_id_mismatch", line_no))
            line = line[:bid[0]]
        if callout == "demonstration":
            continue   # a demonstration's working is not prose with claims; the claim's `demonstration` field is
        line = _REDACTION.sub("", line)
        if tables[i] == _TABLE_ROW:
            if _row_lacks_marker(line, line_no, violations):
                violations.append(("table_row", line_no))
            continue
        if maths[i] == _ROLE_MATHS:
            continue
        if maths[i] == _ROLE_CLOSES:
            at = line.find("$$")
            line = line if at < 0 else line[at + 2:]
        prose = _prose_of(line)
        if prose is not None and _lacks_marker(prose):
            violations.append(("no_claim_marker", line_no))
    return violations


def _wikilinks_outside_code(body):
    """(line, link) for every wikilink or transclusion a reader sees: outside code fences and code spans."""
    spans = _CodeSpans()
    for code, content, _, _ in _read_blocks(dl_lines(body)):
        if code or not content.strip(_WS):
            spans.end_paragraph()
            continue
        text = spans.blank(content)   # a span is blanked in place: every link outside it keeps its indices
        for link in _scan_wikilinks(text):
            yield text, link


def has_transclusion(body):
    """A transclusion `![[…]]` anywhere a reader would embed one, outside code (MarkdownDialect.HasTransclusion)."""
    return any(text[link[0]] == "!" for text, link in _wikilinks_outside_code(body))


# --- citing lines and cells, read per run of markers (MarkdownDialect.Runs, .Cells, .Placement; platform da3a732) --------------
# A citing line is (line, ordinals, folded text, runs): each run a [offset in the folded text, ordinals] for adjacent markers.
_MARKER_CHARACTERS = frozenset("[]^c0123456789")


def _marker_ordinals(text):
    return sorted({int(n) for n in _MARKER.findall(text)})


def _fold_by_runs(raw, rendered, fold):
    """MarkdownDialect.FoldByRuns: the line folded piece by piece between its marker runs, joined by one space wherever
    whitespace separated them, and where each run stands in the result. `rendered` is `raw` with its code spans blanked."""
    if len(raw) != len(rendered):   # never expected: the line whole, one run at its end
        whole = fold(raw)
        return whole, [(len(whole), _marker_ordinals(rendered))]
    runs = []
    for m in _MARKER.finditer(rendered):
        ordinal = int(m.group(1))
        if runs and all(c in _WS_SET for c in rendered[runs[-1][1]:m.start()]):
            if ordinal not in runs[-1][2]:
                runs[-1][2].append(ordinal)
            runs[-1][1] = m.end()
        else:
            runs.append([m.start(), m.end(), [ordinal]])
    folded, result, state = [], [], {"space": False, "length": 0}

    def append(piece):
        text = fold(piece)
        if not text:
            state["space"] |= any(c in _WS_SET for c in piece)
            return
        if state["length"] and (state["space"] or piece[0] in _WS_SET):
            folded.append(" ")
            state["length"] += 1
        folded.append(text)
        state["length"] += len(text)
        state["space"] = piece[-1] in _WS_SET

    frm = 0
    for start, end, ordinals in runs:
        append(raw[frm:start])
        result.append((state["length"], ordinals))
        state["space"] |= any(c not in _MARKER_CHARACTERS for c in rendered[start:end])
        frm = end
    append(raw[frm:])
    return "".join(folded), result


def _read_citing_lines(prose, fold):
    result, callout, spans = [], None, _CodeSpans()
    blocks = _read_blocks(dl_lines(prose))
    tables = _table_roles(blocks)
    for i, (code, content, depth, _) in enumerate(blocks):
        if code or not content.strip(_WS):   # before the callout reset, as the platform reads it: a blank line ends no callout
            spans.end_paragraph()
            continue
        rendered = spans.blank(content)   # a marker inside a code span cites nothing (platform 61a3e57)
        if depth == 0:
            callout = None
        if depth > 0:
            head = _CALLOUT.match(rendered)
            if head:
                callout = head.group(1).lower()
                continue
        text = _after_container_markers(rendered)
        if callout == "demonstration" or _HEADING.match(text) or tables[i] != _TABLE_NONE:
            continue
        ordinals = _marker_ordinals(text)
        if ordinals:
            folded, runs = _fold_by_runs(_after_container_markers(content), text, fold)
            result.append((i + 1, ordinals, folded, runs))
    return result


def citing_lines(prose):
    """MarkdownDialect.CitingLines: every prose line that cites claims — outside code, tables, headings, callout titles and a
    demonstration's working — as (line, ordinals, text as claim_text reads it, runs)."""
    return _read_citing_lines(prose, claim_text)


def legacy_citing_lines(prose):
    """The same lines, their text read by legacy_claim_text: what a line a small edit keeps said when it was published."""
    return _read_citing_lines(prose, legacy_claim_text)


def _cell_ranges(row):
    """Where a table row's cells stand in it, as (start, end) offsets: between unescaped pipes, without the empty cell a
    leading or trailing pipe makes (MarkdownDialect.CellRanges)."""
    frm, to = 0, len(row)
    while frm < to and row[frm] in _WS_SET:
        frm += 1
    while to > frm and row[to - 1] in _WS_SET:
        to -= 1
    cells, start = [], frm
    for k in range(frm, to + 1):
        if k == to or (row[k] == "|" and (k == frm or row[k - 1] != "\\")):
            cells.append((start, k))
            start = k + 1
    if len(cells) > 1 and to > frm and row[frm] == "|":
        cells.pop(0)
    if len(cells) > 1 and to > frm and row[to - 1] == "|" and not (to - 2 >= frm and row[to - 2] == "\\"):
        cells.pop()
    return cells


def citing_cells(prose):
    """MarkdownDialect.CitingCells: every cell of a table's body rows that carries a marker, read as a citing line of its own
    (the owner, 20 Oct 2026) — outside a demonstration's working — with the line of its row."""
    result, callout, spans = [], None, _CodeSpans()
    blocks = _read_blocks(dl_lines(prose))
    tables = _table_roles(blocks)
    for i, (code, content, depth, _) in enumerate(blocks):
        if code or not content.strip(_WS):
            spans.end_paragraph()
            continue
        rendered = spans.blank(content)
        if depth == 0:
            callout = None
        if depth > 0:
            head = _CALLOUT.match(rendered)
            if head:
                callout = head.group(1).lower()
                continue
        if tables[i] != _TABLE_ROW or callout == "demonstration":
            continue
        raw, text = _after_container_markers(content), _after_container_markers(rendered)
        if len(raw) != len(text):
            raw = text   # never expected: the row as shown rather than a misplaced cell boundary
        for start, end in _cell_ranges(text):
            shown = text[start:end]
            ordinals = _marker_ordinals(shown)
            if ordinals:
                folded, runs = _fold_by_runs(raw[start:end], shown, claim_text)
                result.append((i + 1, ordinals, folded, runs))
    return result


def markers_outside_sentences(prose):
    """MarkdownDialect.MarkersOutsideSentences: the 1-based lines carrying a marker where no sentence stands — a heading, a
    table's header or delimiter row, a callout's title (marker_outside_sentence)."""
    result, spans = [], _CodeSpans()
    blocks = _read_blocks(dl_lines(prose))
    tables = _table_roles(blocks)
    for i, (code, content, depth, _) in enumerate(blocks):
        if code or not content.strip(_WS):
            spans.end_paragraph()
            continue
        rendered = spans.blank(content)
        text = _after_container_markers(rendered)
        titled = depth > 0 and _CALLOUT.match(rendered) is not None
        if (titled or _HEADING.match(text) or tables[i] in (_TABLE_HEADER, _TABLE_DELIMITER)) and _MARKER.search(text):
            result.append(i + 1)
    return result


def marked_lines(text):
    """MarkdownDialect.MarkedLines: (line as written, its ordinals) for every line carrying markers outside code."""
    lines, spans, result = dl_lines(text), _CodeSpans(), []
    for line, (code, content, _, _) in zip(lines, _read_blocks(lines)):
        if code or not content.strip(_WS):
            spans.end_paragraph()
            continue
        ordinals = _marker_ordinals(spans.blank(content))
        if ordinals:
            result.append((line, ordinals))
    return result


def _sentence_break_ends(piece):
    """MarkdownDialect.SentenceBreakEnds: just past every terminator followed by whitespace and the start of another
    sentence (a capital, a digit, an opening bracket or quote), an abbreviation's period left out."""
    n, out = len(piece), []
    for i, c in enumerate(piece):
        if c not in ".!?":
            continue
        j = i + 1
        if j < n and piece[j] in "'\"”)":
            j += 1
        k = j
        while k < n and piece[k] in _WS_SET:
            k += 1
        if k == j or k >= n:
            continue
        nxt = piece[k]
        if not ("0" <= nxt <= "9" or nxt in "(\"'" or (nxt <= "\uffff" and unicodedata.category(nxt) == "Lu")):
            continue
        if not _abbreviation_end(piece[max(0, i - 8):i + 1]):
            out.append(i + 1)
    return out


_CLOSERS = frozenset("\"')]”’*_`")
_CLOSING_LOOK_BACK = 4   # closing quotes, brackets and spaces read back from a run before its terminator: bounded


def _ends_sentence_at(text, at):
    i, floor = at, max(0, at - _CLOSING_LOOK_BACK)
    while i > floor and (text[i - 1] in _WS_SET or text[i - 1] in _CLOSERS):
        i -= 1
    if i == 0 or text[i - 1] not in ".!?":
        return False
    return text[i - 1] != "." or not _abbreviation_end(text[max(0, i - 9):i])


def sentence_ends(line):
    """MarkdownDialect.SentenceEnds: where sentences end on a citing line, as offsets into its folded text, ascending —
    past every real sentence break, and at every marker run written after a terminator."""
    _, _, text, runs = line
    return sorted(_sentence_break_ends(text) + [at for at, _ in runs if _ends_sentence_at(text, at)])


def transclusion_lines(body):
    """The 0-based lines the server expands before gate 0: a whole top-level line `![[slug^cN]]` or `![[lang/slug^cN]]`,
    outside code (Transclusion.References)."""
    lines = dl_lines(body)
    return [i for i, (line, block) in enumerate(zip(lines, _read_blocks(lines))) if not block[0] and _TRANSCLUSION_REF.match(line)]


def _unresolvable(m):
    """Why a reference `_TRANSCLUSION_REF` matched can never resolve, or None. References int.Parses the ordinal — a digit
    outside ASCII, or a value past Int32, throws and leaves the whole expansion unresolved — and no claim is numbered 0;
    the resolver compares slug and lang exactly with a page's, which the validator shaped (ExpandAsync, ResolveTransclusionsAsync)."""
    lang, slug, ordinal = m.group(1), m.group(2).strip(_WS), m.group(3)
    digits = ordinal.lstrip("0")
    if not ordinal.isascii():
        return "the ordinal is not written in ASCII digits"
    if not digits or len(digits) > 10 or int(digits) > _INT_MAX:
        return "no claim carries that ordinal"
    if not (_SLUG.fullmatch(slug) and u16(slug) <= LIMITS["slug_max_chars"]):
        return "not a page slug: lowercase letters and digits in hyphen-separated runs"
    if lang is not None and not (_LANG.fullmatch(lang) and u16(lang) <= LIMITS["language_tag_max_chars"]):
        return "not a language tag a page carries"
    return None


# --- front matter (FrontMatter.Parse): `key: value` lines, nine known keys — not YAML ----------------------------------------
FRONT_MATTER_KEYS = ("summary", "wikidata_id", "domain", "lang", "entities", "title", "as_of", "state", "rules_version")


class FrontMatterError(ValueError):
    pass


def _fm_list(values, key):
    v = values.get(key) or ""
    inner = v[1:-1] if len(v) >= 2 and v.startswith("[") and v.endswith("]") else v
    return [p.strip(_WS) for p in inner.split(",") if p.strip(_WS)]


def parse_front_matter(canonical):
    """(front matter, the Markdown after it), or FrontMatterError naming what the platform refuses as invalid_front_matter."""
    text = canonical.replace("\r\n", "\n").lstrip("﻿")
    if not text.startswith("---\n"):
        raise FrontMatterError("the body must start with a --- front matter block")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise FrontMatterError("the front matter block is not closed")
    block, body, values = (text[4:end] if end > 3 else ""), text[end + 5:], {}
    for raw in block.split("\n"):
        line = raw.rstrip(_WS)
        if not line:
            continue
        colon = line.find(":")
        if colon <= 0:
            raise FrontMatterError(f"front matter line is not `key: value`: {line[:60]}")
        key = line[:colon].strip(_WS)
        if key not in FRONT_MATTER_KEYS:
            raise FrontMatterError(f"unknown front matter key: {key[:40]}")
        values[key] = line[colon + 1:].strip(_WS)
    if not values.get("summary"):
        raise FrontMatterError("front matter needs a summary")
    if not values.get("lang"):
        raise FrontMatterError("front matter needs a lang")
    domains = _fm_list(values, "domain")
    unknown = next((d for d in domains if d not in DOMAINS), None)
    if unknown is not None:
        raise FrontMatterError(f"unknown domain: {unknown[:60]}")
    domain = next((d for d in domains if d in SENSITIVE), domains[0] if domains else None)   # the first sensitive one governs
    return ({"summary": values["summary"], "wikidata_id": values.get("wikidata_id") or None, "domain": domain, "domains": domains,
             "lang": values["lang"], "entities": _fm_list(values, "entities"), "title": values.get("title") or None}, body)


def _key_lines(canonical):
    """FrontMatter.KeyLines: (key, value) for every line of the front matter that names a known key, in order."""
    text = canonical.replace("\r\n", "\n").lstrip("﻿")
    if not text.startswith("---\n"):
        return []
    end = text.find("\n---\n", 3)
    if end <= 3:
        return []
    out = []
    for raw in text[4:end].split("\n"):
        line = raw.rstrip(_WS)
        colon = line.find(":")
        if colon > 0 and line[:colon].strip(_WS) in FRONT_MATTER_KEYS:
            out.append((line[:colon].strip(_WS), line[colon + 1:].strip(_WS)))
    return out


def repeated_keys(canonical):
    """FrontMatter.RepeatedKeys: the keys written more than once — the last value governs while a reader sees the first."""
    seen, repeated = set(), []
    for key, _ in _key_lines(canonical):
        if key in seen and key not in repeated:
            repeated.append(key)
        seen.add(key)
    return repeated


def declared_domains(canonical):
    """FrontMatter.DeclaredDomains: every domain any `domain:` line declares, a repetition's earlier lines included."""
    return [d for key, value in _key_lines(canonical) if key == "domain" for d in _fm_list({"domain": value}, "domain")]


def _article_prose(canonical):
    """The body of an article without its front matter; None when it has none that parses (GateZero.ArticleProse)."""
    try:
        return parse_front_matter(canonical)[1]
    except FrontMatterError:
        return None


def domain_of(canonical):
    """FrontMatter.DomainOf: the governing domain of a body that parses, general by default; None when it does not."""
    if canonical is None:
        return None
    try:
        return parse_front_matter(canonical)[0]["domain"] or "general"
    except FrontMatterError:
        return None


def _closing_fence_line(canonical):
    text = canonical.replace("\r\n", "\n").lstrip("﻿")
    if not text.startswith("---\n"):
        return 0
    end = text.find("\n---\n", 3)
    return 0 if end < 0 else text[:end].count("\n") + 2


# --- small edits (UnifiedDiff.Apply and GateZero's reading of a patch) -------------------------------------------------------
_HUNK = re.compile(r"@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(?: .*)?")
_INT_MAX = 2 ** 31 - 1


class PatchError(ValueError):
    pass


def apply_patch(base, patch):
    """The article a patch produces from its base, exactly as the platform merges it; PatchError when it does not apply."""
    a = base.replace("\r\n", "\n").split("\n")
    result, pos, in_hunk, old_left, new_left = [], 0, False, 0, 0
    for line in patch.replace("\r\n", "\n").split("\n"):
        if line.startswith("@@"):
            if old_left or new_left:
                raise PatchError("incomplete hunk")
            m = _HUNK.fullmatch(line)
            if not m:
                raise PatchError("malformed hunk header")
            first, old_left, new_first, new_left = (int(m.group(1)), int(m.group(2) or "1"), int(m.group(3)), int(m.group(4) or "1"))
            if max(first, old_left, new_first, new_left) > _INT_MAX:
                raise PatchError("malformed hunk header")
            start = first if old_left == 0 else first - 1
            new_start = new_first if new_left == 0 else new_first - 1
            if start < pos or start > len(a) or old_left > len(a) - start:
                raise PatchError("hunk out of order")
            if new_start != len(result) + start - pos:
                raise PatchError("inconsistent destination range")
            result.extend(a[pos:start])
            pos, in_hunk = start, True
            continue
        if not in_hunk or not line:
            continue
        text, c = line[1:], line[0]
        if c in " -":
            if old_left == 0 or (c == " " and new_left == 0):
                raise PatchError("hunk exceeds its declared range")
            if pos >= len(a) or a[pos] != text:
                raise PatchError(f"the patch does not match the base at line {pos + 1}")
            if c == " ":
                result.append(text)
                new_left -= 1
            old_left -= 1
            pos += 1
        elif c == "+":
            if new_left == 0:
                raise PatchError("hunk exceeds its declared range")
            result.append(text)
            new_left -= 1
        elif c != "\\":
            raise PatchError("malformed patch line")
    if old_left or new_left:
        raise PatchError("incomplete hunk")
    result.extend(a[pos:])
    return "\n".join(result)


def _hunk_lines(patch, context):
    """What a patch keeps, read as the merge reads it: inside a hunk the first character alone decides."""
    in_hunk = False
    for line in patch.split("\n"):
        if line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line and (line[0] == "+" or (context and line[0] == " ")):
            yield line[0], line[1:]


def kept_lines(patch):
    return "\n".join(text for _, text in _hunk_lines(patch, True))


def _new_side(patch):
    """[(sign, text, settled, framed)] for the lines of kept_lines, in order. `settled`: an empty line of the same hunk
    stands above the line, so whatever makes it a table row, a demonstration's working or display maths begins inside the
    hunk, where a reading without base.md sees it — an empty line ends a table, a quote and maths. `framed`: not settled,
    and a line of the hunk up to this one is quoted or has a cell boundary, so a callout title or a table header above
    the hunk may reach it. Only a fence runs across an empty line: one opened above the hunk is what this reading cannot
    see (base.md beside the proposal can)."""
    out, in_hunk, empty, framed = [], False, False, False
    for line in patch.split("\n"):
        if line.startswith("@@"):
            in_hunk, empty, framed = True, False, False
        elif in_hunk and line and line[0] in "+ ":
            text = line[1:]
            # a row has a pipe of its own; the one in [[slug|label]] is prose's
            framed = not empty and (framed or _quote_markers(text, 1 << 30, False)[0] > 0 or _has_cell_boundary(_without_wikilinks(text)))
            out.append((line[0], text, empty, framed))
            empty = empty or not text.strip(_WS) or bool(_FM_LINE.match(text))
    return out


def _added_lines(patch):
    """[(text, its line in the merged article, or None under a header that does not parse)]."""
    out, in_hunk, nxt = [], False, None
    for line in patch.split("\n"):
        if line.startswith("@@"):
            in_hunk = True
            m = _HUNK.fullmatch(line)
            nxt = int(m.group(3)) if m and int(m.group(3)) <= _INT_MAX else None
            continue
        if not in_hunk or not line:
            continue
        if line[0] == "+":
            out.append((line[1:], nxt))
            nxt = None if nxt is None else nxt + 1
        elif line[0] == " ":
            nxt = None if nxt is None else nxt + 1
    return out


_FM_LINE = re.compile(r"(?:%s):" % "|".join(FRONT_MATTER_KEYS))


# --- gate 0 --------------------------------------------------------------------------------------------------------------------
_WHY = {
    "raw_html": "raw HTML is rejected at gate 0, not sanitised; write the Markdown dialect (markdown.md §6)",
    "hidden_text": "a character a reader cannot see (raw_html): write plain text (markdown.md §6)",
    "no_claim_marker": "a sentence without its [^cN] marker, a second sentence before one, or words after the last marker — one sentence per line (markdown.md §2)",
    "table_row": "a table row that states something in words cites a claim, and each marked cell ends in its marker (no_claim_marker, markdown.md §6)",
    "block_id_mismatch": "the block id ^cN must repeat the line's last marker [^cN] (markdown.md §2)",
    "unknown_callout": "only [!disputed] and [!demonstration] (markdown.md §5)",
    "external_link": "a link out of Scio, an autolink or a hand-written footnote or reference definition — evidence goes in claims and the references are generated (markdown.md §3, §6)",
    "external_image": "an image that is not exactly ![alt](media:<sha256>.<ext>) after scio_upload_media (media_unverified, markdown.md §6)",
}
_REASON = {"hidden_text": "raw_html", "table_row": "no_claim_marker", "external_image": "media_unverified"}


def _dialect_problem(kind, where, text):
    excerpt = text.strip()[:70]
    return f"gate 0 refuses {_REASON.get(kind, kind)} — {where}: \"{excerpt}\" — {_WHY[kind]}"


# --- a small edit is one (SmallEditScope, BaseClaims; BP-08, the owner's decisions of 20 Oct 2026) ---------------------------
def _tokens(text):
    """TextNormalizer.Tokens: runs of letters and digits (one UTF-16 unit each), lower-cased."""
    out, current = [], []
    for c in text:
        if c <= "￿" and (c.isalpha() or _is_digit16(c)):
            low = c.lower()
            current.append(low if len(low) == 1 else c)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


_SCOPE_BLOCK_ID = re.compile(r"\s*\^c\d+(?=\s|$)")


def _scope_read(prose):
    """SmallEditScope.Read: the words each ordinal's markers close, the words no marker closes, and every sentence."""
    by_ordinal, loose, sentences, fence = {}, [], [], False
    for raw in prose.split("\n"):
        line = raw.strip(_WS)
        if line.startswith("```"):
            fence = not fence
            continue
        if not line:
            continue
        if fence or line.startswith("#"):
            block = " ".join(_tokens(line))
            if block:
                sentences.append(block)
            continue
        line = _SCOPE_BLOCK_ID.sub("", line)
        start = 0
        for m in re.finditer(r"\[\^c(\d+)\]", line):
            words = " ".join(_tokens(line[start:m.start()]))
            by_ordinal.setdefault(m.group(1), []).append(words)
            sentences.append(words)
            start = m.end()
        rest = " ".join(_tokens(line[start:]))
        if rest:
            loose.append(rest)
            sentences.append(rest)
    return by_ordinal, loose, sentences


def small_edit_exceeds(base_prose, merged_prose, submitted):
    """SmallEditScope.Exceeds: whether the claims an edit removes or adds — the ones it supplies anew counted as replaced —
    or the sentences it adds pass max(limits.small_edit_min_changed_claims, share × the base's): a rewrite is an article."""
    share, floor = LIMITS["small_edit_max_changed_share"], LIMITS["small_edit_min_changed_claims"]
    keys = {str(o) for o in submitted}
    before, after = _scope_read(base_prose), _scope_read(merged_prose)
    units = lambda p: Counter([" | ".join(v) for k, v in p[0].items() if k not in keys] + p[1])
    excess = lambda a, b: sum(max(0, n - b[k]) for k, n in a.items())
    bound = lambda n: max(floor, int(share * n))
    claims_before, claims_after = units(before), units(after)
    removed = excess(claims_before, claims_after) + sum(1 for k in before[0] if k in keys)
    added = excess(claims_after, claims_before) + len(keys)
    if max(removed, added) > bound(len(before[0]) + len(before[1])):
        return True
    return excess(Counter(after[2]), Counter(before[2])) > bound(len(before[2]))


def _same_source(a, b):
    return (a is None and b is None) or a == b or same_document(a, b)


def _demonstration_key(d):
    return None if not isinstance(d, dict) else tuple(d.get(k) for k in ("method", "text", "checker", "artifact_sha256", "output"))


def _premise_keys(premises):
    return [(p.get("claim_ordinal"), p.get("source_url", p.get("source")), p.get("quote")) for p in (premises or []) if isinstance(p, dict)]


def _recites(base, c):
    """ClaimRecital.Recites: the claim the edit supplies carries everything authored about the base claim at its ordinal.
    The base claim is read as scio_get_claims serves it (`source`, `second_source`), which carries no wikidata_id."""
    bp, cp = _premise_keys(base.get("premises")), _premise_keys(c.get("premises"))
    return (base.get("ordinal") == c.get("ordinal") and base.get("text") == c.get("text")
            and (base.get("kind") or "sourced") == (c.get("kind") or "sourced")
            and _same_source(base.get("source_url", base.get("source")), c.get("source_url"))
            and base.get("quote") == c.get("quote")
            and _same_source(base.get("second_source_url", base.get("second_source")), c.get("second_source_url"))
            and base.get("second_quote") == c.get("second_quote")
            and ("wikidata_id" not in base or base.get("wikidata_id") == c.get("wikidata_id"))
            and base.get("origin_claim_id") == c.get("origin_claim_id") and base.get("scope") == c.get("scope")
            and _demonstration_key(base.get("demonstration")) == _demonstration_key(c.get("demonstration"))
            and len(bp) == len(cp) and all(x[0] == y[0] and _same_source(x[1], y[1]) and x[2] == y[2] for x, y in zip(bp, cp)))


def changed_ordinals(claims, base_claims):
    """SmallEditScope.ChangedOrdinals: the ordinals of the claims the edit lists anew rather than re-citing as the base has
    them; every one when the base's claims are not known."""
    by = {}
    for b in base_claims or []:
        if isinstance(b, dict) and isinstance(b.get("ordinal"), int):
            by.setdefault(b["ordinal"], b)
    return {c["ordinal"] for c in claims if isinstance(c.get("ordinal"), int) and not (c["ordinal"] in by and _recites(by[c["ordinal"]], c))}


_TITLE_HEADING = re.compile(r" {0,3}#(?:[ \t]|$)")


def article_title(prose):
    """MarkdownDialect.Title: the first non-empty level-one ATX heading a reader sees — outside code, quotes and display
    maths — without its closing run of `#`; None when there is none."""
    blocks = _read_blocks(dl_lines(prose))
    maths = _closed_maths(blocks)
    for (code, content, depth, _), role in zip(blocks, maths):
        if code or depth > 0 or role != _ROLE_NONE:
            continue
        opening = _TITLE_HEADING.match(content)
        if not opening:
            continue
        text = content[opening.end():].strip(_WS)
        run = len(text)
        while run > 0 and text[run - 1] == "#":
            run -= 1
        if run < len(text) and (run == 0 or text[run - 1] in " \t"):
            text = text[:run].rstrip(_WS)
        if text:
            return text
    return None


def changes_identity(base, merged):
    """SmallEditScope.ChangesIdentity: the edit retitles the page (front matter or heading), moves its entity or changes
    its linked entities — an article's to make (the owner, 20 Oct 2026)."""
    try:
        (bf, bb), (af, ab) = parse_front_matter(base), parse_front_matter(merged)
    except FrontMatterError:
        return False
    return (bf["wikidata_id"] != af["wikidata_id"] or bf["title"] != af["title"] or article_title(bb) != article_title(ab)
            or set(bf["entities"]) != set(af["entities"]))


# --- one document, two spellings (SourceIdentity.SameDocument): second_source_not_independent ------------------------------------
_TRACKERS = frozenset("fbclid gclid dclid gbraid wbraid msclkid mc_cid mc_eid igshid yclid twclid _ga _gl".split())


def _document_key(url):
    if not isinstance(url, str):
        return None
    try:
        p = urlparse(url.strip(_WS))
        host, port = p.hostname, p.port
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not host:
        return None
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        host = host.lower()
    host = host[4:] if host.startswith("www.") else host
    default = {"http": 80, "https": 443}[p.scheme.lower()]
    path = p.path or "/"
    path = path.rstrip("/") if len(path) > 1 else ""
    query = sorted(q for q in p.query.split("&") if q and not (q.split("=", 1)[0].lower().startswith("utm_") or q.split("=", 1)[0].lower() in _TRACKERS))
    return host + ("" if port in (None, default) else f":{port}") + path + ("?" + "&".join(query) if query else "")


def same_document(a, b):
    """Two URLs of one document: host without www., port, path without its trailing slash, the query without trackers and
    in order — the fragment never counts. A second source is another document (SEC-AUDIT)."""
    ka, kb = _document_key(a), _document_key(b)
    return ka is not None and ka == kb


def _forbidden(url):
    """ForbiddenSources.IsForbidden over the signed host list, on the host's IDNA form as the platform reads it (Uri.IdnHost:
    ｗｉｋｉｐｅｄｉａ。org is wikipedia.org), plus the Wikimedia wiki pages the plugin keeps out too (P7) — by host and path,
    not by a mention in the query."""
    host = source_host(url)
    try:
        host = host.encode("idna").decode("ascii").rstrip(".")
    except UnicodeError:
        pass
    return bool(host) and (any(host == f or host.endswith("." + f) for f in FORBIDDEN_HOSTS)
                           or ((host == "wikimedia.org" or host.endswith(".wikimedia.org")) and urlparse(url).path.lower().startswith("/wiki")))


def _claim_texts(c):
    d = c.get("demonstration") if isinstance(c.get("demonstration"), dict) else {}
    premises = c.get("premises") if isinstance(c.get("premises"), list) else []
    return [t for t in [c.get("text"), c.get("quote"), c.get("second_quote"), d.get("text"), d.get("output"), c.get("scope")]
            + [p.get("quote") for p in premises if isinstance(p, dict)] if isinstance(t, str)]


def gate_zero(inp, claims, base=None, page_domain=None, base_claims=None):
    """(problems, notes): what gate 0 refuses, named by its reason, and what the pre-flight could not read the way the gate
    will. `base` is the canonical body of the revision a small edit lands on; `page_domain` the page's domain when known;
    `base_claims` the base revision's claims as scio_get_claims serves them (which of the edit's claims merely re-cite one)."""
    problems, notes = [], []
    kind = inp.get("kind")
    body = inp.get("body") if kind != "small_edit" else None     # ProposalShape.ForKind: a kind carries one text only
    body_in = body
    patch = inp.get("patch") if kind not in ("article", "translation") else None
    if body is not None and patch is not None and kind is None:
        patch = None
    summary = inp.get("summary") if isinstance(inp.get("summary"), str) else ""
    ordinals = {c["ordinal"] for c in claims if isinstance(c.get("ordinal"), int)}

    # The server expands every whole-line `![[slug^cN]]` into the origin's sentence and a claim of its own before this gate.
    # Offline nothing resolves, so those lines are set aside: a line without letters stands where the sentence will. Only a
    # reference that could resolve is set aside; one no page can answer is the gate's transclusion_unresolved already.
    if body is not None:
        lines = dl_lines(body)
        original = list(lines)
        refs = transclusion_lines(body)
        for i in refs:
            lines[i] = "0"
        if refs:
            body = "\n".join(lines)
            if len(refs) + len(claims) > LIMITS["claims_per_proposal"]:
                problems.append(f"gate 0 refuses transclusion_unresolved — {len(refs)} transclusions and {len(claims)} claims exceed the "
                                f"{LIMITS['claims_per_proposal']} claims a proposal may carry once they are expanded")
            dead = [f"{m.group(0).strip(_WS)[:60]} ({why})" for m in (_TRANSCLUSION_REF.match(original[i]) for i in refs)
                    for why in [_unresolvable(m)] if why]
            if dead:
                problems.append(f"gate 0 refuses transclusion_unresolved — {'; '.join(dead[:4])}: no page can answer it; write "
                                "`![[slug^cN]]` or `![[lang/slug^cN]]`, a page's slug and a claim ordinal from 1 (markdown.md §4)")
    reviewer_material = "\n".join(t for t in (body, patch) if isinstance(t, str))

    merged = None
    if patch is not None and base is not None:
        try:
            merged = apply_patch(base, patch)
        except PatchError as e:
            notes.append(f"the patch does not apply to base.md ({e}): read on its own lines instead — the platform answers "
                         "conflict when it does not apply to the revision either")
    fm = result_fm = None
    fm_error, added_fm, offset = None, "", 0
    if body is not None:
        try:
            fm, prose = parse_front_matter(body)
            result_fm, offset = fm, _closing_fence_line(body)
        except FrontMatterError as e:
            fm_error = str(e)
            end = body.find("\n---\n", 3) if body.startswith("---\n") else -1
            prose, offset = (body[end + 5:], body[:end].count("\n") + 2) if end >= 0 else (body, 0)
    else:
        added = _added_lines(patch or "")
        if merged is not None:
            fence = 0
            try:
                result_fm, fence = parse_front_matter(merged)[0], _closing_fence_line(merged)
            except FrontMatterError as e:
                fm_error = str(e)
            prose = "\n".join(t for t, n in added if n is None or n > fence)
            added_fm = "\n".join(t for t, n in added if n is not None and n <= fence)
        else:   # no base: the added lines are the prose, but a known key or a fence is front matter, as the merge would place it
            prose = "\n".join(t for t, _ in added if not (_FM_LINE.match(t) or t.strip() == "---"))
            added_fm = "\n".join(t for t, _ in added if _FM_LINE.match(t))
    if fm_error:
        problems.append(f"gate 0 refuses invalid_front_matter — {fm_error}; front matter is `key: value` lines only — the keys "
                        f"{', '.join(FRONT_MATTER_KEYS)}, summary and lang required, lists in brackets, no comments, block lists, "
                        "block scalars or quotes, domain from " + ", ".join(DOMAINS) + " (markdown.md §1)")
    resulting = body_in if body_in is not None else merged
    if resulting is not None:
        repeated = [k for k in repeated_keys(resulting) if k not in repeated_keys(base or "")]
        if repeated:
            problems.append(f"gate 0 refuses front_matter_duplicate_key — {', '.join(repeated)} written twice in the front matter: the "
                            "last value would govern while a reader sees the first; keep one line per key (markdown.md §1)")

    base_prose = _article_prose(base) if base is not None else None
    merged_prose = _article_prose(merged) if body is None and merged is not None else None
    if kind == "small_edit" and merged_prose is not None and base_prose is not None:
        known = base_claims is not None
        exceeds = small_edit_exceeds(base_prose, merged_prose, changed_ordinals(claims, base_claims))
        if exceeds and not known and not small_edit_exceeds(base_prose, merged_prose, set()):
            notes.append("gate 0 may refuse not_a_small_edit — the edit changes more than a small edit may unless the claims it "
                         "lists re-cite the base's exactly as stored; put the base revision's claims (scio_get_claims) beside "
                         "proposal.json as base-claims.json and the pre-flight reads which ones it re-cites (maintain.md)")
        elif exceeds:
            problems.append(f"gate 0 refuses not_a_small_edit — the edit removes, replaces or adds more claims or sentences than "
                            f"max({LIMITS['small_edit_min_changed_claims']}, {LIMITS['small_edit_max_changed_share']:g} × the base's) "
                            "(limits.small_edit_max_changed_share): a rewrite is an article — propose kind article (maintain.md)")
    if kind == "small_edit" and merged is not None and base is not None:
        if ((domain_of(base) or "general") in SENSITIVE or any(d in SENSITIVE for d in declared_domains(base))) \
                and domain_of(merged) is not None and domain_of(merged) not in SENSITIVE \
                and not any(d in SENSITIVE for d in declared_domains(merged)):
            problems.append("gate 0 refuses not_a_small_edit — the edit takes the page out of its sensitive domain: an article's to make "
                            "(Part V)")
        if changes_identity(base, merged):
            problems.append("gate 0 refuses not_a_small_edit — the edit changes the page's title, its heading, its wikidata_id or its "
                            "entities: a small edit corrects a page, it never retitles it or moves it to another entity — propose an "
                            "article (the owner, 20 Oct 2026)")

    # the dialect
    settled, framed = set(), set()   # without base.md: kept lines read in what their hunk shows, or maybe not (_new_side)
    if body is not None:
        prose_lines = dl_lines(prose)
        for k, line_no in dialect_check(prose):
            problems.append(_dialect_problem(k, f"body line {line_no + offset}", prose_lines[line_no - 1]))
    elif merged_prose is not None:
        before, after = dl_lines(base_prose or ""), dl_lines(merged_prose)
        same = lambda k: "no_claim_marker" if k == "table_row" else k   # one kind on the platform, however this port words it
        carried = Counter((same(k), before[n - 1]) for k, n in dialect_check(base_prose or ""))
        for k, n in dialect_check(merged_prose):   # a violation the base already carried on the same line is not the edit's
            if carried[(same(k), after[n - 1])] > 0:
                carried[(same(k), after[n - 1])] -= 1
            else:
                problems.append(_dialect_problem(k, "in the merged article", after[n - 1]))
    else:   # no base: the new side of each hunk, context included, so a working line or a table row keeps its surroundings
        # — the ones the hunk shows. A table header, a callout title or display maths above the hunk is unknown here, and
        # the platform reads the line in the merged article: whether a line must end in a marker depends on them, unless an
        # empty line of the hunk stands above it. That finding is a warning then; the others are read on the line itself.
        side, added_at = [], set()
        for sign, text, after_empty, in_frame in _new_side(patch or ""):
            if sign == "+" and not (_FM_LINE.match(text) or text.strip() == "---"):
                added_at.add(len(side) + 1)
            if after_empty:
                settled.add(len(side) + 1)
            if in_frame:
                framed.add(len(side) + 1)
            side.append("" if _FM_LINE.match(text) and sign == " " else text)
        for k, n in dialect_check("\n".join(side)):
            if n in added_at:
                problem = _dialect_problem(k, "an added line (read without base.md)", side[n - 1])
                if k in ("no_claim_marker", "table_row") and n not in settled:
                    notes.append(problem.replace("gate 0 refuses", "gate 0 may refuse", 1))
                else:
                    problems.append(problem)

    # a marker in a heading, a table's header row or a callout's title cites a claim where no sentence is compared with it
    for line in _new_markers_outside_sentences(base_prose if merged_prose is not None else None, merged_prose if merged_prose is not None else prose):
        problems.append(f"gate 0 refuses marker_outside_sentence — a claim marker in a heading, a table's header row or a callout's "
                        f"title: \"{line.strip(_WS)[:80]}\" — cite the claim at the end of the sentence that states it (markdown.md §2)")

    if has_transclusion(prose):
        problems.append("gate 0 refuses transclusion_unresolved — only a line of its own, `![[slug^cN]]` or `![[lang/slug^cN]]`, "
                        "outside any quote, callout, list or sentence, is expanded; any other ![[…]] is left unresolved (markdown.md §4)")

    # the front-matter summary, whenever the submission writes it: the dialect's markup rules, at most three sentences and
    # limits.summary_max_chars characters, every sentence closed by a claim marker (D45, the owner, 20 Oct 2026)
    base_summary = None
    if base is not None:
        try:
            base_summary = parse_front_matter(base)[0]["summary"]
        except FrontMatterError:
            pass
    written_summary = result_fm["summary"] if result_fm and result_fm["summary"] != base_summary else None
    if written_summary is None and body is None and merged is None:   # no base: a summary line the patch adds is read alone
        added_summary = next((t[len("summary:"):].strip(_WS) for t in reversed(added_fm.split("\n")) if t.startswith("summary:")), None)
    else:
        added_summary = None
    for text, refuse in ((written_summary, True), (added_summary, False)):
        if text is None:
            continue
        found = []
        kinds = {k for k, _ in dialect_check(text) + dialect_check("S " + text)}
        for k in ("hidden_text", "raw_html", "external_image", "external_link"):
            if k in kinds:
                found.append(_dialect_problem(k, "the front-matter summary", text))
        sentences, unmarked, chars = summary_sentences(text)
        if sentences > LIMITS["summary_max_sentences"] or chars > LIMITS["summary_max_chars"]:
            found.append(f"gate 0 refuses summary_too_long — the front-matter summary holds {sentences} sentence(s) and {chars:,} characters; "
                         f"at most {LIMITS['summary_max_sentences']} and {LIMITS['summary_max_chars']:,} (limits.summary_max_sentences, "
                         "summary_max_chars), image alt text counted. \". \" ends a sentence there whatever word it closes: write "
                         "abbreviations out (\"Doctor Smith\", not \"Dr. Smith\") — markdown.md §2a")
        if unmarked:
            found.append("gate 0 refuses summary_unmarked — every sentence of the front-matter summary ends in a claim marker, [^cN] "
                         "right after its full stop; \". \" ends a sentence there whatever word it closes (write \"Doctor Smith\", not "
                         "\"Dr. Smith\"), and an image's alt text that reads as a sentence is one no marker closes (markdown.md §2a)")
        for f in found:
            (problems if refuse else notes).append(f if refuse else f.replace("gate 0 refuses", "gate 0 may refuse", 1)
                                                   + " (a summary line the patch adds, read without base.md)")

    # every marker the submission writes resolves to a listed claim — prose, added front-matter lines, a summary it writes,
    # and the lines a patch writes into the article it merges into; every listed claim is used
    marked = body if (body is not None and fm_error) else prose   # an unparsed front matter is read as prose, summary and all
    written = markers(marked) + markers(added_fm)
    if fm and fm["summary"] != base_summary:
        written += markers(fm["summary"])
    if merged_prose is not None:
        written += _changed_line_markers(base_prose or "", merged_prose)
    stray = sorted(set(written) - ordinals)
    if stray:
        problems.append(f"gate 0 refuses no_claim_marker — markers without a listed claim: {stray[:8]} — every claim a sentence the "
                        "submission writes cites is listed, a base claim re-listed exactly as stored (maintain.md)")
    used = set(markers(kept_lines(patch or "")) if body is None else markers(marked))
    if fm:
        used |= set(markers(fm["summary"]))
    unused = sorted(ordinals - used)
    if unused:
        problems.append(f"gate 0 refuses unused_claim — claims cited by no sentence{' the patch keeps (added or context lines)' if body is None else ''}: "
                        f"{unused[:8]}")
    if fm_error is None:
        citing = prose if body is not None else (merged_prose if merged_prose is not None else kept_lines(patch or ""))
        legacy = _unchanged_citing_lines(base_prose or "", merged_prose) if body is None and merged_prose is not None else None
        strict = _claim_text_mismatches(claims, citing, legacy, changed_ordinals(claims, base_claims) if legacy is not None else None)
        lenient = set()
        if legacy is not None and base_claims is None:   # unknown which claims re-cite the base's: a kept line may read as published
            lenient = {m for _, m, _ in _claim_text_mismatches(claims, citing, legacy, set())}
        for line_no, m, message in strict:
            # without base.md, a line under quoted lines may be a demonstration's working and one under table rows a row of
            # its own — CitingLines reads neither as a sentence — when the callout title or the header stands above the hunk
            if body is None and merged is None and line_no in framed:
                notes.append(message.replace("gate 0 refuses", "gate 0 may refuse", 1))
            elif legacy is not None and base_claims is None and m not in lenient:
                notes.append(message.replace("gate 0 refuses", "gate 0 may refuse", 1) + " — unless the claim re-cites the base's exactly "
                             "as stored (base-claims.json beside proposal.json lets the pre-flight read which)")
            else:
                problems.append(message)
    if body is None and merged is None and any(n.startswith("gate 0 may refuse") for n in notes):
        notes.insert(0, "the patch is read without base.md, a hunk at a time: a fence, a table header or a callout title above a hunk "
                        "is unknown here, so what depends on one is only a warning — put the text of base_revision beside "
                        "proposal.json as base.md and propose with proposal_file, and the patch is read in its article (maintain.md)")
    if result_fm and result_fm["wikidata_id"] is not None and not _WIKIDATA.fullmatch(result_fm["wikidata_id"]):
        problems.append(f"gate 0 refuses invalid_wikidata_id — wikidata_id {result_fm['wikidata_id'][:40]!r} is not a Wikidata id (Q and its digits, "
                        "no leading zero)")
    if result_fm:
        inherited = set()
        if body is None and base is not None:
            try:
                inherited = set(parse_front_matter(base)[0]["entities"])
            except FrontMatterError:
                pass
        bad = [e for e in result_fm["entities"] if not _WIKIDATA.fullmatch(e) and e not in inherited]
        if bad:
            problems.append(f"gate 0 refuses invalid_wikidata_id — entities are Wikidata ids (Q and its digits, no leading zero), not {bad[0][:40]!r}")
    if has_hidden_text(summary):
        problems.append("gate 0 refuses raw_html — a character a reader cannot see in the summary; write plain text (markdown.md §6)")
    if has_hidden_text(reviewer_material) and not any("a character a reader cannot see" in p for p in problems):
        problems.append(f"gate 0 refuses raw_html — a character a reader cannot see in the {'body' if body is not None else 'patch'} "
                        "(front matter and diff headers included); write plain text (markdown.md §6)")

    if body is None and merged is not None:
        media = article_media_references(merged)   # the cap is the article's: a patch is counted on what the merge produces
    else:
        media = list(dict.fromkeys(media_references(prose) + media_references(fm["summary"] if fm else "")))
    if len(media) > LIMITS["media_max_per_article"]:
        problems.append(f"gate 0 refuses too_many_media — {len(media)} images; an article holds at most {LIMITS['media_max_per_article']} (media.max_per_article)")
    if _REVIEWER.search(reviewer_material) or _REVIEWER.search(summary):
        problems.append("gate 0 refuses reviewer_instruction — text addressed to the reviewers is refused and penalised (security.md §4)")

    # every domain a repeated key declares counts too, which the parser's last value hides (the owner, 20 Oct 2026)
    declared = [d for t in (body_in, base, merged) if isinstance(t, str) for d in declared_domains(t)]
    sensitive = any(d in SENSITIVE for d in ((fm or {}).get("domain"), page_domain, domain_of(base), domain_of(merged), *declared))
    for i, c in enumerate(claims):
        n = c.get("ordinal", i)
        urls = [c.get("source_url"), c.get("second_source_url")] + [p.get("source_url") for p in (c.get("premises") if isinstance(c.get("premises"), list) else []) if isinstance(p, dict)]
        for u in urls:
            if isinstance(u, str) and u and _forbidden(u):
                problems.append(f"gate 0 refuses forbidden_source — claim {n} cites {source_host(u)}, a forbidden source host (P7: no Wikipedia, no Grokipedia, no mirrors, no Scio itself)")
        if sensitive and c.get("kind") != "demonstrated" and not (isinstance(c.get("second_source_url"), str) and c["second_source_url"].strip()):
            why = next(d for d in ((fm or {}).get("domain"), page_domain, domain_of(base), domain_of(merged), *declared) if d in SENSITIVE)
            problems.append(f"gate 0 refuses missing_second_source — claim {n}: domain '{why}' needs a second independent source (Part V)")
        if c.get("second_source_url") is not None and same_document(c.get("source_url"), c.get("second_source_url")):
            problems.append(f"gate 0 refuses second_source_not_independent — claim {n}: the second source is the first one written "
                            "again (one document under two spellings); cite another document (Part V)")
        if any(_REVIEWER.search(t) for t in _claim_texts(c)):
            problems.append(f"gate 0 refuses reviewer_instruction — claim {n} addresses the reviewers (security.md §4)")
        d = c.get("demonstration") if isinstance(c.get("demonstration"), dict) else {}
        if any(has_hidden_text(t) for t in _claim_texts(c) + [d.get("checker") if isinstance(d.get("checker"), str) else ""]):
            problems.append(f"gate 0 refuses raw_html — claim {n} carries a character a reader cannot see; write plain text (markdown.md §6)")
        if c.get("kind") == "demonstrated":
            for p in (c.get("premises") if isinstance(c.get("premises"), list) else []):
                if isinstance(p, dict) and p.get("claim_ordinal") is not None and isinstance(p["claim_ordinal"], int) and isinstance(n, int) \
                        and (p["claim_ordinal"] >= n or p["claim_ordinal"] not in ordinals):
                    problems.append(f"gate 0 refuses premise_unresolved — claim {n} rests on claim {p['claim_ordinal']}, which is not an earlier "
                                    "claim of this proposal (C10: nothing is assumed silently)")
    return list(dict.fromkeys(problems)), notes


def _first_at_least(values, at):
    return bisect.bisect_left(values, at)


def _first_run_from(runs, at, limit):
    """The first run, at or before `limit`, whose offset is at least `at`; `limit` when none is."""
    lo, hi = 0, limit
    while lo < hi:
        mid = (lo + hi) // 2
        if runs[mid][0] >= at:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _terminator_before(text, at):
    i, floor = at, max(0, at - _CLOSING_LOOK_BACK)
    while i > floor and (text[i - 1] == " " or text[i - 1] in _CLOSERS):
        i -= 1
    return i > 0 and text[i - 1] in ".!?"


def _sentence_before(line, at, marked, ends):
    """The stretch of the folded line that leads to the run at `at`, from the last sentence end before it."""
    e = _first_at_least(ends, at) - 1
    start = max(marked, ends[e] if e >= 0 else 0)
    return line[2][start:at].strip(" ")


def _reaches(line, text, after, end):
    if not text or len(text) > end:
        return False
    return line.find(text, max(0, after - len(text) + 1), end) >= 0


def _inline_premises(line, texts, premises):
    """GateZero.InlinePremises: per run, the markers read as premises cited inline there — inside the sentence of a
    demonstrated claim marked at the same run or a later one that rests on them; None when the line has none."""
    text, runs = line[2], line[3]
    spans, ends = None, None
    for q, (at, ordinals) in enumerate(runs):
        for d in ordinals:
            rests, claim = premises.get(d), texts.get(d)
            if not rests or not claim:
                continue
            previous = runs[q - 1][0] if q > 0 else 0
            frm = max(0, previous - len(claim) + 1)
            if len(claim) > at - frm:
                continue
            start = text.find(claim, frm, at)
            if start < 0:
                continue
            lo = _first_run_from(runs, start + 1, q)
            if ends is None:
                ends = sentence_ends(line)
            e = _first_at_least(ends, start + 1)
            until = min(_first_run_from(runs, ends[e], q), q) if e < len(ends) else q
            spans = spans or []
            if lo < until:
                spans.append((lo, until - 1, rests))
            spans.append((q, q, rests))   # a premise written beside the demonstrated claim stands in its sentence
    if spans is None:
        return None
    result, open_ = [None] * len(runs), Counter()
    for r in range(len(runs)):
        for frm, _, rests in spans:
            if frm == r:
                open_.update(rests)
        for m in runs[r][1]:
            if open_[m] > 0:
                result[r] = (result[r] or set()) | {m}
        for _, until, rests in spans:
            if until == r:
                open_.subtract(rests)
    return result


def _mismatched(line, texts, premises, legacy=None, published=None):
    """GateZero.Mismatched: (ordinal, the sentence its marker closes, or None for a legacy reading) for every listed claim
    a citing line or cell does not say, per marker occurrence."""
    if published is not None and len(published[0][3]) != len(line[3]):
        published = None   # never expected: read the line strictly rather than misplace a run
    inline = _inline_premises(line, texts, premises)
    ends, closed, marked = None, 0, 0
    for r, (at, ordinals) in enumerate(line[3]):
        closes = False
        for m in ordinals:
            if inline is not None and inline[r] is not None and m in inline[r]:
                continue
            closes = True
            if m not in texts:
                continue   # an unlisted marker is no_claim_marker's, or a base claim the edit carries
            if legacy is not None and legacy(m):
                says = (_reaches(published[0][2], published[1][m], closed, published[0][3][r][0]) if published is not None
                        else _reaches(line[2], texts[m], closed, at))
                if not says:
                    yield m, None
                continue
            if ends is None:
                ends = sentence_ends(line)
            sentence = _sentence_before(line, at, marked, ends)
            if not texts[m] or sentence != texts[m]:
                yield m, sentence
        if closes:
            closed = published[0][3][r][0] if published is not None else at
            if _terminator_before(line[2], at):   # a run after a terminator ends a sentence; a clause cited mid-sentence none
                marked = at


def _claim_text_mismatches(claims, prose, legacy_lines=None, rewritten=None):
    """GateZero.ClaimTextMismatches: a claim's text is the whole sentence that cites it — every occurrence of its marker, on a
    prose line or in a table cell, is preceded by exactly the claim's text from where the last sentence ended (markers and
    block id dropped, whitespace collapsed, nothing else changed) — save a premise cited inline in the sentence of the
    demonstrated claim that rests on it. `legacy_lines`: the lines of `prose` a patch kept as the base had them, read as
    they were published, save for the claims in `rewritten`. [(1-based line, ordinal, the refusal)]."""
    texts, premises = {}, {}
    for c in claims:
        if not isinstance(c.get("ordinal"), int):
            continue
        texts.setdefault(c["ordinal"], claim_text(c.get("text") if isinstance(c.get("text"), str) else ""))
        if c.get("kind") == "demonstrated":
            premises.setdefault(c["ordinal"], {p["claim_ordinal"] for p in (c.get("premises") if isinstance(c.get("premises"), list) else [])
                                               if isinstance(p, dict) and isinstance(p.get("claim_ordinal"), int)})
    legacy_by_line = legacy_texts = None
    if legacy_lines:
        legacy_by_line = {l[0]: l for l in legacy_citing_lines(prose)}
        legacy_texts = {}
        for c in claims:
            if isinstance(c.get("ordinal"), int):
                legacy_texts.setdefault(c["ordinal"], legacy_claim_text(c.get("text") if isinstance(c.get("text"), str) else ""))
    refused, out = set(), []

    def refuse(line_no, m, sentence, where):
        if m in refused:
            return
        refused.add(m)
        if sentence is None:
            why = f"its text is not found in the kept line it cites, \"{legacy_by_line[line_no][2][:90]}\""
        elif not sentence:
            why = "its marker closes no sentence: the text before it is another claim's or nothing"
        else:
            why = f"the {where} that cites it reads \"{sentence[:160]}\"; write the claim's text exactly so"
        out.append((line_no, m, f"gate 0 refuses claim_text_mismatch — claim {m}: {why} (the whole sentence up to its marker, "
                                 "as written — case, emphasis, code marks, wikilinks and quotes included; only whitespace "
                                 "is normalised — markdown.md §2)"))

    for line in citing_lines(prose):
        as_published = ((lambda o: rewritten is None or o not in rewritten)
                        if legacy_lines is not None and line[0] in legacy_lines else None)
        published = ((legacy_by_line[line[0]], legacy_texts)
                     if as_published is not None and legacy_by_line is not None and line[0] in legacy_by_line else None)
        for m, sentence in _mismatched(line, texts, premises, as_published, published):
            refuse(line[0], m, sentence, "sentence")
    for cell in citing_cells(prose):
        kept = legacy_lines is not None and cell[0] in legacy_lines
        for m, sentence in _mismatched(cell, texts, premises):
            if kept and not (rewritten is not None and m in rewritten):
                continue
            refuse(cell[0], m, sentence, "table cell")
    return out


def _unchanged_citing_lines(base_prose, merged_prose):
    """The 1-based lines of the merged prose that are, as written, lines of the base carrying markers."""
    before = {line for line, _ in marked_lines(base_prose)}
    return {i + 1 for i, line in enumerate(dl_lines(merged_prose)) if line in before}


def _changed_line_markers(base_prose, merged_prose):
    """The markers on merged lines that are not, as written, lines of the base carrying markers: what a patch writes."""
    before = {line for line, _ in marked_lines(base_prose)}
    return [m for line, ordinals in marked_lines(merged_prose) if line not in before for m in ordinals]


def _new_markers_outside_sentences(before, after):
    """GateZero.MarkersOutsideSentences: the lines of `after` with a marker where no sentence stands, less those `before`
    already carried word for word — published text is not re-gated. [(line text)]."""
    after_lines, carried = dl_lines(after), Counter()
    if before is not None:
        before_lines = dl_lines(before)
        carried.update(before_lines[n - 1] for n in markers_outside_sentences(before))
    out = []
    for n in markers_outside_sentences(after):
        text = after_lines[n - 1]
        if carried[text] > 0:
            carried[text] -= 1
        else:
            out.append(text)
    return out


# --- the front-matter summary (MarkdownDialect.SummarySentences; D45, enforced 20 Oct 2026) ----------------------------------
def _without_embeds(text, alts):
    """Every image `![alt](…)` and transclusion `![[…]]` replaced by a space — shown, not said — save an image's alt text,
    which goes to `alts`. A `![` that opens neither is left as written."""
    at = text.find("![")
    if at < 0:
        return text
    out, frm = [], 0
    while at >= 0:
        if text.startswith("![[", at):
            close = text.find("]]", at + 3)
            end = -1 if close < 0 else close + 2
        else:
            bracket = text.find("]", at + 2)
            paren = -1 if bracket < 0 or bracket + 1 >= len(text) or text[bracket + 1] != "(" else text.find(")", bracket + 2)
            end = -1 if paren < 0 else paren + 1
            if end >= 0:
                alts.append(text[at + 2:bracket])
        if end < 0:
            break
        out.append(text[frm:at] + " ")
        frm = end
        at = text.find("![", frm)
    return "".join(out) + text[frm:]


def _summary_break_ends(piece):
    r"""`[.!?][^\s\p{L}\p{N}]*\s+\S` matched without overlap: just past each terminator followed, after any non-letters, by
    whitespace and anything — no abbreviation or lower-case exemption in the summary."""
    out, i, n = [], 0, len(piece)
    while i < n:
        if piece[i] in ".!?":
            j = i + 1
            while j < n and piece[j] not in _WS_SET and not (piece[j] <= "\uffff" and unicodedata.category(piece[j])[0] in "LN"):
                j += 1
            k = j
            while k < n and piece[k] in _WS_SET:
                k += 1
            if k > j and k < n:
                out.append(i + 1)
                i = k + 1
                continue
        i += 1
    return out


def _is_digit16(c):
    return unicodedata.category(c) == "Nd"


def _ends_in_terminator(text):
    i = len(text)
    while i > 0 and (text[i - 1] in _WS_SET or text[i - 1] in _CLOSERS):
        i -= 1
    return i > 0 and text[i - 1] in ".!?"


def _has_words(text):
    """char.IsLetterOrDigit of any UTF-16 unit: a letter or a decimal digit, which punctuation and spaces alone never are."""
    return any(c <= "\uffff" and (c.isalpha() or _is_digit16(c)) for c in text)


def summary_sentences(summary):
    """MarkdownDialect.SummarySentences: (sentences, whether one lacks its closing marker, characters said). A sentence ends
    at every terminator before whitespace — an abbreviation's period too —, at a marker run right after a terminator, or at
    the end; images and transclusions are not sentences, but an image's alt text is said: it counts toward the characters,
    and an alt text that reads as a sentence is one no marker closes. Code spans are code; a wikilink reads as its label."""
    alts = []
    text = _without_wikilinks(_without_embeds(_CodeSpans().blank(summary), alts))
    pieces = _MARKER.split(text)   # the captured ordinals interleave: every odd piece is one
    sentences, unmarked = 0, any(_summary_break_ends(a) or _ends_in_terminator(a) for a in alts)
    open_ = cited = False
    for i in range(0, len(pieces), 2):
        piece, frm = pieces[i], 0
        for end in _summary_break_ends(piece):
            words = _has_words(piece[frm:end])
            if words or open_:
                sentences += 1
                unmarked |= words or not cited
            open_, cited, frm = False, False, end
        if _has_words(piece[frm:]):
            open_, cited = True, False
        if i == len(pieces) - 1:
            break
        cited |= open_   # a marker follows the piece
        if open_ and _ends_in_terminator(piece):
            sentences += 1
            open_, cited = False, False
    if open_:
        sentences += 1
        unmarked |= not cited
    return sentences, unmarked, u16(text.strip(_WS)) + sum(u16(a.strip(_WS)) for a in alts)


# ==================================================================================================================
# the proposal validator (ProposeEditValidator): refused before quota, but refused — and the agent should know why here
# ==================================================================================================================
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_WIKIDATA = re.compile(r"Q[1-9][0-9]{0,18}")   # WikidataIds.Pattern: canonical, no leading zero, at most 20 characters
_LANG = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")


def _blank(v):
    return not (isinstance(v, str) and v.strip(_WS))


def _absolute_url(u):
    try:
        p = urlparse(u)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


_URL_CAP = (f"at most {LIMITS['url_max_chars']:,} characters (limits.url_max_chars), on one line, with no control or invisible "
            "character")


def _plain_url(u):
    """WebUrls.IsPlain within limits.url_max_chars: a URL is stored, fetched and served back to every reader and reviewer."""
    return u16(u) <= LIMITS["url_max_chars"] and not any(c in u for c in "\t\n\r") and not has_hidden_text(u)


def shaped(inp):
    """ProposalShape.ForKind: a kind carries only its own fields — the platform drops the others unread, before validating."""
    drop = {"small_edit": ("body", "translation_of", "gap_id"), "article": ("patch", "translation_of"), "translation": ("patch",)}.get(inp.get("kind"), ())
    return {k: v for k, v in inp.items() if k not in drop}


def admission(inp, claims):
    """What ProposeEditValidator refuses in the fields present. A field the contract requires but the call lacks is the
    contract's to demand (the MCP schema refuses it, free); the pre-flight judges what the proposal says."""
    out = []
    inp = shaped(inp)

    def bad(field, msg):
        out.append(f"validation_failed — {field}: {msg} (the platform refuses the call before quota)")

    kind = inp.get("kind")
    if "kind" in inp and kind not in ("article", "small_edit", "translation"):
        bad("kind", "must be one of: article, small_edit, translation")
    if "slug" in inp and not (isinstance(inp["slug"], str) and u16(inp["slug"]) <= LIMITS["slug_max_chars"] and _SLUG.fullmatch(inp["slug"])):
        bad("slug", f"lowercase letters and digits in hyphen-separated runs (no leading, trailing or double hyphen), at most {LIMITS['slug_max_chars']} characters")
    if "lang" in inp and not (isinstance(inp["lang"], str) and u16(inp["lang"]) <= LIMITS["language_tag_max_chars"] and _LANG.fullmatch(inp["lang"])):
        bad("lang", f"a BCP-47 tag like en or pt-BR, at most {LIMITS['language_tag_max_chars']} characters (limits.language_tag_max_chars)")
    if "summary" in inp:
        if _blank(inp["summary"]):
            bad("summary", "must not be empty")
        elif u16(inp["summary"]) > LIMITS["proposal_summary_max_chars"]:
            bad("summary", f"{u16(inp['summary'])} characters; at most {LIMITS['proposal_summary_max_chars']}")
    for field, pat in (("base_revision", r"rv_[a-z0-9_]{1,64}"), ("mission_id", r"tk_[0-9a-f]{1,32}"), ("gap_id", r"gp_[0-9a-f]{16}")):
        if inp.get(field) is not None and not (isinstance(inp[field], str) and re.fullmatch(pat, inp[field])):
            bad(field, f"must match {pat}" + (" — the ticket id (ref_id tk_…) of the error report, not the task id" if field == "mission_id" else ""))
    media = inp.get("media")
    for j, m in enumerate(media if isinstance(media, list) else ([] if media is None else [media])):
        if not (isinstance(m, str) and re.fullmatch(r"[0-9a-f]{64}\.(svg|png|jpg|webp)", m)):
            bad(f"media[{j}]", "<sha256>.<svg|png|jpg|webp>")
    if isinstance(inp.get("idempotency_key"), str) and not 8 <= u16(inp["idempotency_key"]) <= 128:
        bad("idempotency_key", "8 to 128 characters")
    if kind in ("article", "translation") and _blank(inp.get("body")):
        bad("body", "required for articles and translations")
    if kind == "small_edit":
        if _blank(inp.get("patch")):
            bad("patch", "required for small edits")
        if _blank(inp.get("base_revision")):
            bad("base_revision", "a small edit is always against a revision")
    if kind == "translation" and _blank(inp.get("translation_of")):
        bad("translation_of", "required for translations")
    for field in ("body", "patch"):
        if isinstance(inp.get(field), str):
            if u16(inp[field]) > LIMITS["body_max_chars"]:
                bad(field, f"{u16(inp[field]):,} characters; at most {LIMITS['body_max_chars']:,} (limits.body_max_chars) — split the article")
            cap = LIMITS["line_max_chars"] + (1 if field == "patch" else 0)   # a diff line carries its one prefix character
            if any(u16(line) > cap for line in inp[field].split("\n")):
                bad(field, f"no line may exceed {LIMITS['line_max_chars']:,} characters — one sentence per line")
    if not claims:
        bad("claims", "must not be empty — a small edit that only removes text re-lists, unchanged, a claim the patch keeps on a context line")
    if len(claims) > LIMITS["claims_per_proposal"]:
        bad("claims", f"{len(claims)} claims; at most {LIMITS['claims_per_proposal']} per proposal — split the article")
    urls = {u for c in claims for u in [c.get("source_url"), c.get("second_source_url")]
            + [p.get("source_url") for p in (c.get("premises") if isinstance(c.get("premises"), list) else []) if isinstance(p, dict)]
            if isinstance(u, str) and u}
    premises_total = sum(len(c["premises"]) for c in claims if isinstance(c.get("premises"), list))
    if premises_total > LIMITS["premises_per_proposal"]:
        bad("claims", f"{premises_total} premises across the claims; at most {LIMITS['premises_per_proposal']} per proposal (limits.premises_per_proposal)")
    if len(urls) > LIMITS["distinct_sources_per_proposal"]:
        bad("claims", f"{len(urls)} distinct source URLs (premises and second sources included); at most {LIMITS['distinct_sources_per_proposal']}")
    tmax, qmax, dmax, smax = LIMITS["claim_text_max_chars"], LIMITS["claim_quote_max_chars"], LIMITS["demonstration_max_chars"], LIMITS["scope_max_chars"]
    for i, c in enumerate(claims):
        at, demonstrated = f"claims[{i}]", c.get("kind") == "demonstrated"
        if _blank(c.get("text")):
            bad(f"{at}.text", "must not be empty")
        for f, cap in (("text", tmax), ("quote", qmax), ("second_quote", qmax), ("scope", smax)):
            if isinstance(c.get(f), str) and u16(c[f]) > cap:
                bad(f"{at}.{f}", f"{u16(c[f])} characters; at most {cap:,}")
        if (not demonstrated or c.get("quote") is not None) and _blank(c.get("source_url")):
            bad(f"{at}.source_url", "a sourced claim or a supplied quote requires its source")
        for f in ("source_url", "second_source_url"):
            if isinstance(c.get(f), str) and c[f] and not _absolute_url(c[f]):
                bad(f"{at}.{f}", "must be an absolute http(s) URL")
            if isinstance(c.get(f), str) and not _plain_url(c[f]):
                bad(f"{at}.{f}", _URL_CAP)
        if (not demonstrated or c.get("source_url") is not None) and _blank(c.get("quote")):
            bad(f"{at}.quote", "a sourced claim or a supplied source requires the exact quote (not blank)")
        if (not demonstrated or c.get("source_url") is not None) and not c.get("accessed_at"):
            bad(f"{at}.accessed_at", "required with a source")
        if (c.get("second_source_url") is not None) != (c.get("second_quote") is not None) or \
                (c.get("second_source_url") is not None and (_blank(c.get("second_source_url")) or _blank(c.get("second_quote")))):
            bad(f"{at}.second_source_url", "a second source and its exact quote go together")
        if c.get("wikidata_id") is not None and not (isinstance(c["wikidata_id"], str) and _WIKIDATA.fullmatch(c["wikidata_id"])):
            bad(f"{at}.wikidata_id", "a Wikidata id: Q and its digits, as Wikidata writes it (no leading zero)")
        if not demonstrated:
            for f in ("premises", "demonstration", "scope"):
                if c.get(f) is not None:
                    bad(f"{at}.{f}", f"only a demonstrated claim has {f}")
            continue
        premises = c.get("premises")
        if not (isinstance(premises, list) and premises):
            bad(f"{at}.premises", "a demonstrated claim states its premises: earlier claims by ordinal, or cited spans (C10)")
        elif len(premises) > LIMITS["premises_per_claim"]:
            bad(f"{at}.premises", f"{len(premises)} premises; at most {LIMITS['premises_per_claim']} per claim (limits.premises_per_claim)")
        for j, p in enumerate(premises if isinstance(premises, list) else []):
            if not isinstance(p, dict):
                bad(f"{at}.premises[{j}]", "must be an object (claim.schema.json)")
                continue
            is_claim = p.get("claim_ordinal") is not None
            if is_claim == (p.get("source_url") is not None or p.get("quote") is not None):
                bad(f"{at}.premises[{j}]", "a premise is either an earlier claim (claim_ordinal) or a cited source (source_url + quote), never both (C10)")
            elif not is_claim:
                if not (isinstance(p.get("source_url"), str) and _absolute_url(p["source_url"])):
                    bad(f"{at}.premises[{j}].source_url", "must be an absolute http(s) URL")
                elif not _plain_url(p["source_url"]):
                    bad(f"{at}.premises[{j}].source_url", _URL_CAP)
                if _blank(p.get("quote")) or u16(p["quote"]) > qmax:
                    bad(f"{at}.premises[{j}].quote", f"a cited premise carries the exact span (at most {qmax:,} characters)")
        d = c.get("demonstration")
        if not isinstance(d, dict):
            bad(f"{at}.demonstration", "a demonstrated claim carries its demonstration")
        else:
            machine = d.get("method") in ("proof_assistant", "program")
            if not machine and _blank(d.get("text")):
                bad(f"{at}.demonstration.text", "a written proof or calculation is its text")
            if machine and _blank(d.get("checker")):
                bad(f"{at}.demonstration.checker", "a machine-checked demonstration names its checker and version")
            for f in ("text", "output"):
                if isinstance(d.get(f), str) and u16(d[f]) > dmax:
                    bad(f"{at}.demonstration.{f}", f"{u16(d[f]):,} characters; at most {dmax:,} (limits.demonstration_max_chars)")
            if d.get("artifact_sha256") is not None and not (isinstance(d["artifact_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", d["artifact_sha256"])):
                bad(f"{at}.demonstration.artifact_sha256", "64 lowercase hex digits")
        if _blank(c.get("scope")):
            bad(f"{at}.scope", "a demonstrated claim states the model and conditions under which it holds")

    def nul(node, path):
        if isinstance(node, str) and "\0" in node:
            bad(path, "U+0000 cannot be stored; remove it")
        elif isinstance(node, dict):
            for k, v in node.items():
                nul(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for j, v in enumerate(node):
                nul(v, f"{path}[{j}]")
    nul(inp, "")
    return out


# ==================================================================================================================
# the proposal as it arrives, and the plugin's own rules on top of gate 0
# ==================================================================================================================
def load(argv):
    """(scio_propose_edit input, hook mode, the file the proposal came from or None)."""
    if len(argv) > 1:
        with open(argv[1], encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("proposal must be a JSON object")
        return data.get("tool_input", data), False, argv[1]
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be a JSON object")
    inp = payload.get("tool_input", {})
    if isinstance(inp, dict) and isinstance(inp.get("proposal_file"), str):   # scio_propose_edit by file: pre-flight what the bridge will send
        try:
            if not inside_work_root(inp["proposal_file"]):
                raise ValueError("proposal_file must be inside the task work root")
            with open(inp["proposal_file"], encoding="utf-8") as f:
                proposal = json.load(f)
            if not isinstance(proposal, dict):
                raise ValueError("proposal_file must hold a JSON object")
            return {**proposal, **{k: v for k, v in inp.items() if k != "proposal_file"}}, True, inp["proposal_file"]
        except (OSError, ValueError) as e:
            return {"body": "", "claims": [], "_unreadable": f"proposal_file could not be read ({e})"}, True, None
    return inp, True, None


def base_beside(proposal_file, name="base.md"):
    """base.md (or `name`) in the proposal's own task folder — a regular file there, never a link out of it — or None. Only
    a proposal in the task work root has a task folder: the check quotes the lines it reads, so a base.md beside a file
    elsewhere (the system's temporary directory, shared with every user) is never read, as --base names only a file in the root."""
    if not proposal_file or not inside_work_root(proposal_file):
        return None
    folder = os.path.dirname(os.path.abspath(proposal_file))
    path = os.path.join(folder, name)
    if not os.path.isfile(path) or os.path.islink(path) or os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder):
        return None
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def base_claims_beside(proposal_file):
    """The base revision's claims, from base-claims.json beside the proposal — scio_get_claims' answer saved as it came, or
    its `claims` array — or None when there is none or it is not a list of claims."""
    raw = base_beside(proposal_file, "base-claims.json")
    if raw is None:
        return None
    try:
        data = json.loads(raw.lstrip("\ufeff"))
    except ValueError:
        return None
    claims = data.get("claims") if isinstance(data, dict) else data
    return [c for c in claims if isinstance(c, dict)] if isinstance(claims, list) else None


def type_errors(value, schema, path):
    """Check types before content rules perform string operations or arithmetic."""
    expected = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int}
    if expected in types and type(value) is not types[expected]:
        article = "a" if expected == "string" else "an"
        return [f"{path}: must be {article} {expected} (claim.schema.json)"]
    errors = []
    if expected == "object":
        for name, child_schema in schema.get("properties", {}).items():
            if name in value:
                errors.extend(type_errors(value[name], child_schema, f"{path}.{name}"))
    elif expected == "array":
        for index, item in enumerate(value):
            errors.extend(type_errors(item, schema.get("items", {}), f"{path}[{index}]"))
    elif expected == "integer" and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: must be at least {schema['minimum']} (claim.schema.json)")
    return errors


def source_host(url):
    """The host a URL really points at — parsed, not split on strings: `https://wikipedia.org#@evil.example/` is
    wikipedia.org (the fragment hides the @), `https://wikipedia.org./wiki/X` is wikipedia.org (trailing dot)."""
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _prose_lines(prose):
    """(line, is a table row) for every line that holds sentences: outside code, headings, table headers, callout titles and
    a demonstration's working — what the style rules and the one-sentence-per-line rule read. Code spans are blanked, as
    the platform reads markers (61a3e57): an example's words and markers are not the line's."""
    blocks = _read_blocks(dl_lines(prose))
    tables, callout, out, spans = _table_roles(blocks), None, [], _CodeSpans()
    for i, (code, content, depth, _) in enumerate(blocks):
        if code or not content.strip(_WS):
            spans.end_paragraph()
        if code:
            continue
        if depth == 0:
            callout = None
        rendered = spans.blank(content)
        head = _CALLOUT.match(rendered) if depth > 0 else None
        if head:
            callout = head.group(1).lower()
            continue
        text = _after_container_markers(rendered)
        if callout == "demonstration" or _HEADING.match(text) or tables[i] in (_TABLE_HEADER, _TABLE_DELIMITER):
            continue
        out.append((text, tables[i] == _TABLE_ROW))
    return out


def check(inp, base=None, page_domain=None, base_claims=None):
    problems, warnings = [], []
    if not isinstance(inp, dict):
        return ["proposal must be a JSON object"], []
    if inp.get("_unreadable"):
        return [inp["_unreadable"]], []
    for field in ("body", "patch", "summary"):
        if field in inp and inp[field] is not None and not isinstance(inp[field], str):
            problems.append(f"{field} must be a string")
    if problems:
        return problems, []
    claims = inp.get("claims", [])
    if not isinstance(claims, list):
        return ["claims must be a list (claim.schema.json)"], []
    for index, claim in enumerate(claims):
        problems.extend(type_errors(claim, _SCHEMA, f"claim {index}"))
    if problems:
        return problems, []

    # --- the claims' shape (claim.schema.json) and the constitution's rules on a demonstration ------------------------------
    body_in = shaped(inp).get("body")
    doc_sensitive = any(d in SENSITIVE for d in (domain_of(body_in) if isinstance(body_in, str) else None, page_domain, domain_of(base)))
    by_ordinal = {}
    for i, c in enumerate(claims):
        if isinstance(c.get("ordinal"), int):
            if c["ordinal"] in by_ordinal:
                problems.append(f"claims[{i}]: ordinal {c['ordinal']} is used twice — every claim its own number (markdown.md §2)")
            by_ordinal[c["ordinal"]] = c
        elif "ordinal" in c:
            problems.append(f"claims[{i}]: ordinal must be an integer ≥ 1 (claim.schema.json)")
        else:
            problems.append(f"claims[{i}]: missing ordinal")
        kind = c.get("kind", "sourced")
        if kind not in CLAIM_KINDS:
            problems.append(f"claims[{i}]: kind must be sourced or demonstrated, not {kind!r} (claim.schema.json)")
        unknown = sorted(set(c) - CLAIM_PROPS)
        if unknown:
            problems.append(f"claims[{i}]: unknown propert{'y' if len(unknown) == 1 else 'ies'} {', '.join(unknown)} (claim.schema.json allows no extra properties)")
        if kind == "demonstrated":
            d = c.get("demonstration") if isinstance(c.get("demonstration"), dict) else {}
            methods = set(_SCHEMA["properties"]["demonstration"]["properties"]["method"]["enum"])
            if d and d.get("method") not in methods:
                problems.append(f"claims[{i}]: demonstration.method must be one of {', '.join(sorted(methods))} (claim.schema.json)")
            extra = sorted(set(d) - set(_SCHEMA["properties"]["demonstration"]["properties"]))
            if extra:
                problems.append(f"claims[{i}]: demonstration has unknown propert{'y' if len(extra) == 1 else 'ies'} {', '.join(extra)} (claim.schema.json)")
            if d.get("method") in ("proof_assistant", "program") and not (d.get("checker") and d.get("output")):
                problems.append(f"claims[{i}]: a {d.get('method')} demonstration needs checker and output (C10)")
            if d.get("method") in ("proof", "calculation") and len(d.get("text") or "") < 40:
                problems.append(f"claims[{i}]: the demonstration text is too short to re-derive (C10)")
            for j, p in enumerate(c.get("premises") if isinstance(c.get("premises"), list) else []):
                extra = sorted(set(p) - set(_SCHEMA["properties"]["premises"]["items"]["properties"])) if isinstance(p, dict) else []
                if extra:
                    problems.append(f"claims[{i}]: premise {j} has unknown propert{'y' if len(extra) == 1 else 'ies'} {', '.join(extra)} (claim.schema.json)")
            if doc_sensitive:
                warnings.append(f"claims[{i}]: demonstrated claim in a sensitive domain — observations there are sourced, not derived (C10, Part V)")
            continue
        if c.get("second_source_url") and c.get("source_url") and \
           re.sub(r"^www\.", "", source_host(str(c["second_source_url"]))) == re.sub(r"^www\.", "", source_host(str(c["source_url"]))):
            warnings.append(f"claims[{i}]: both sources are on the same host — are they independent (S3)?")
        q, t = (c.get("quote") or ""), (c.get("text") or "")
        if q and t:
            nums = [n.rstrip(".,") for n in re.findall(r"\d[\d,.]*", t)]
            missing_nums = [n for n in nums if n not in q]
            if missing_nums:  # report a measurement before a year: that is where precision drifts
                worst = sorted(missing_nums, key=lambda n: bool(re.fullmatch(r"(19|20)\d{2}", n)))[0]
                warnings.append(f"claims[{i}]: number {worst} in the sentence is not in the quote — check precision (C1, C4)")

    # --- what the platform refuses: admission, then gate 0 ------------------------------------------------------------------
    problems.extend(admission(inp, claims))
    gate_problems, notes = gate_zero(inp, claims, base=base, page_domain=page_domain, base_claims=base_claims)
    problems.extend(gate_problems)
    warnings[0:0] = notes   # what the pre-flight could not read the way the gate will comes first, before the style notes
    # a character nobody sees is refused wherever it hides, URLs and ids included (a superset of gate 0's fields, same set)
    def hidden(node, path):
        if isinstance(node, str):
            return [path] if has_hidden_text(node) else []
        if isinstance(node, dict):
            return [p for k, v in node.items() for p in hidden(v, f"{path}.{k}")]
        if isinstance(node, list):
            return [p for j, v in enumerate(node) for p in hidden(v, f"{path}[{j}]")]
        return []
    elsewhere = [p for p in hidden({k: v for k, v in shaped(inp).items() if k not in ("body", "patch", "summary")}, "$") if not re.search(r"\.(text|quote|second_quote|scope|output|checker)$", p)]
    if elsewhere:
        problems.append(f"hidden or format character in {elsewhere[0][2:]} — write plain text")
    # a code point this Python calls unassigned, which the platform's newer Unicode may have assigned: named, not refused
    def strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, (dict, list)):
            for v in (node.values() if isinstance(node, dict) else node):
                yield from strings(v)
    newer = next((ch for s in strings(shaped(inp)) for ch in [unvouched(s)] if ch), None)
    if newer:
        warnings.insert(len(notes), f"U+{ord(newer):04X} is unassigned in this Python's Unicode {unicodedata.unidata_version}, older than "
                                    f"the platform's {'.'.join(map(str, PLATFORM_UNICODE))}: gate 0 refuses it as raw_html (hidden text) "
                                    "unless that Unicode assigned it — keep it only if it is the character you meant (markdown.md §6)")

    # --- what the platform already said about these sources (the bridge records every scio_verify_source verdict) ---
    # The gates run the same fetch and the same quote match on the proposal: a pair they will refuse is an error here,
    # before it costs the day's quota unit; a pair nobody verified is named, because that is where proposals die.
    pair_verdicts, url_verdicts = read_verdicts()
    unverified, spans = [], 0
    for i, c in enumerate(claims):
        # named by its marker, the sentence the agent must fix; by its place when the ordinal is unusable
        name = f"[^c{c['ordinal']}]" if type(c.get("ordinal")) is int and c["ordinal"] >= 1 else f"claims[{i}]"
        cited = [("", c.get("source_url"), c.get("quote")), ("second ", c.get("second_source_url"), c.get("second_quote"))]
        cited += [("premise's ", p.get("source_url"), p.get("quote")) for p in (c.get("premises") if isinstance(c.get("premises"), list) else []) if isinstance(p, dict)]
        for which, u, q in cited:   # gate 2 retrieves all three kinds of span
            if not (isinstance(u, str) and u.strip() and isinstance(q, str) and q.strip()):
                continue
            spans += 1
            url_id, pair_id = source_ids(u, q)
            about_source, about_quote = url_verdicts.get(url_id), pair_verdicts.get(pair_id)
            if about_source and about_source["status"] in ("dead", "likely_fabricated", "forbidden_source"):
                problems.append(f"{name}: scio_verify_source found the {which}source '{about_source['status']}' — gate 1 refuses it; re-source the sentence "
                                "(never with an archived_url: that is Scio's own copy, a forbidden source; maintain.md)")
            elif about_source and about_source.get("reliability") in ("blacklisted", "deprecated"):
                problems.append(f"{name}: scio_verify_source rates the {which}source '{about_source['reliability']}' — gate 4 refuses it (source_blacklisted); use another source")
            elif about_quote and about_quote.get("quote_found") is None and about_quote["status"] == "live":
                # a verdict for a pair is recorded only when a quote was given: live, a quote, and no answer about it means
                # the platform extracted no text from the page (VerifySource scores against ExtractedText, or not at all)
                problems.append(f"{name}: scio_verify_source could extract no text from the {which}source (a PDF or another binary format?) — gate 1 refuses it "
                                "(unsupported_source_format); cite a page that carries the same words as text")
            elif about_quote and about_quote.get("quote_found") is False:
                score = f" (match {about_quote['match_score']})" if about_quote.get("match_score") is not None else ""
                problems.append(f"{name}: scio_verify_source did not find the {which}quote in its source{score} — gate 2 refuses it (quote_not_found); "
                                "quote the source's exact words and verify again")
            elif not about_quote or about_quote.get("quote_found") is not True:
                unverified.append(name)
            elif about_source and about_source.get("reliability") == "generally_unreliable":
                warnings.append(f"{name}: the {which}source is rated generally_unreliable — unfit for a lone claim (write.md step 3)")
    if unverified:
        which = list(dict.fromkeys(unverified))
        warnings.insert(0, f"{len(unverified)} of {spans} source/quote pairs have no scio_verify_source verdict from the last 7 days in this workspace "
                           f"({', '.join(which[:10])}{'…' if len(which) > 10 else ''}): the gates fetch every one, and a single quote they cannot find "
                           "fails the proposal and spends the quota unit — verify each pair first, with the quote (write.md step 3)")

    # --- the dialect's own conventions and the constitution's style, on the lines that hold sentences ---------------------------
    kind = inp.get("kind")
    body = inp.get("body") if kind != "small_edit" and isinstance(inp.get("body"), str) else None
    patch = inp.get("patch") if kind not in ("article", "translation") and isinstance(inp.get("patch"), str) else None
    if body is not None:
        text = body
        try:
            prose = parse_front_matter(body)[1]
        except FrontMatterError:
            end = body.find("\n---\n", 3) if body.startswith("---\n") else -1
            prose = body[end + 5:] if end >= 0 else body
    else:
        text = patch or ""
        prose = "\n".join(t for s, t in _hunk_lines(text, False) if not (_FM_LINE.match(t) or t.strip() == "---"))
    summary_text = inp.get("summary") if isinstance(inp.get("summary"), str) else ""
    sentences = []
    for line, row in _prose_lines(prose):
        bid = block_id(line)
        fns = _MARKER.findall(line)
        cells = _cells(line) if row else [line[:bid[0]] if bid else line]
        for cell in cells:
            sentences += [p.strip() for p in _MARKER.split(_without_wikilinks(cell))[::2] if _has_letter(p)]
        if row:
            continue   # a table row cites one claim per cell
        own = by_ordinal.get(int(fns[-1])) if fns else None
        # a demonstrated sentence cites its premises inline ("By [^c3] and [^c4], … .[^c5] ^c5", style.md)
        premise_cites = (len(fns) > 1 and bid and bid[1] == fns[-1] and isinstance(own, dict) and own.get("kind") == "demonstrated"
                         and all(int(f) < int(fns[-1]) for f in fns[:-1]))
        if len(fns) > 1 and not premise_cites:
            problems.append(f"two claims on one line — one sentence per line: \"{line.strip()[:60]}…\" (markdown.md §2)")
        elif fns and not bid:
            warnings.append(f"claim [^c{fns[-1]}] has no block id ^c{fns[-1]} at the end of its line (markdown.md §2)")
    # with the linear scanner, as the platform reads links: a pattern whose class crossed line ends cost minutes on a body of `[[a`
    for line, (start, end, ts, te, _) in _wikilinks_outside_code(prose):
        target = line[ts:te].strip(_WS)
        if not re.fullmatch(r"([a-z]{2,3}(-[A-Za-z0-9]{2,8})*/)?[a-z0-9][a-z0-9-]*", target):
            warnings.append(f"wikilink target '{target[:60]}' is not a slug (lowercase, hyphens, optional lang/ prefix)")
        if line[start] == "!" and re.search(r"\.(png|jpg|jpeg|svg|webp|gif)$", line[start + 3:end - 2], re.I):
            problems.append("file embeds ![[…]] are not allowed; use ![alt](media:<sha256>.<ext>) after scio_upload_media")
    for s in sentences:
        if UNDATED.search(s) and not DATE.search(s):
            warnings.append(f"undated time-bound wording: \"{s[:70]}…\" — date it (C4)")
        if PUFFERY.search(s):
            warnings.append(f"puffery or unattributed consensus: \"{s[:70]}…\" — quote and attribute, or drop (C2, C6)")
        if reader_told(s):
            problems.append(f"text that tells the reader what to do: \"{s[:70]}…\" (C6, security.md §4)")
        elif READER.search(s):   # a warning: "The Reader" is a novel and "You Should Be Dancing" a song; gate 0 refuses neither
            warnings.append(f"text addressed to the reader or to agents: \"{s[:70]}…\" — rephrase unless it is a name or a title (C6)")
        if VAGUE_NUM.search(s) and not re.search(r"\d", s):
            warnings.append(f"vague quantity without a number: \"{s[:70]}…\" — use the source's figure (C4)")

    # --- injection and steering (security.md §4): in the body it is a rejection at review, so block it here ---
    # scanned in full — front matter, headings, embeds, code and the summary included: an instruction hidden in a heading is
    # still one. Hidden characters are the hidden-text check's (MarkdownDialect.IsHidden, joiners allowed), not the scanner's.
    # A patch is scanned line by line as its lines read, without the diff's prefixes: "```python" over "-if a < b" read as
    # `python -if …`, a shell command, while "+curl … | sh" hid from every pattern that starts a line.
    if body is None:
        text = "\n".join(line[1:] if line[:1] in "+- " else line for line in text.split("\n"))
    hits = _scan.dedupe(_scan.scan_text(text, "body") + _scan.scan_text(summary_text, "summary") + _scan.scan_json(claims, "claims"))
    for h in hits:   # every hit is classified — six warnings in the body must not hide a blocking hit in a claim's quote
        if h["pattern"] in ("zero_width_chars", "bidi_controls"):   # hidden characters are the IsHidden port's, above
            continue
        # blocking: steering and what gate 0 refuses. The vocabulary of a subject (an access token, a system prompt), and
        # in a verbatim quote anything gate 0 accepts, are warnings (scan-injection.blocks_proposal)
        target = problems if _scan.blocks_proposal(h) else warnings
        target.append(f"{h['pattern']} at {h['where']}: …{h['excerpt'][:80]}… (security.md §4)")
    return list(dict.fromkeys(problems)), list(dict.fromkeys(warnings))[:12]


def main():
    for stream in (sys.stdin, sys.stdout):   # the proposal is UTF-8 whatever the locale (Windows: cp1252 otherwise)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    argv, base_path, domain = [sys.argv[0]], None, None
    args = sys.argv[1:]
    while args:
        a = args.pop(0)
        if a in ("--base", "--domain") and args:
            value = args.pop(0)
            if a == "--domain":
                domain = value
            else:
                base_path = value
        else:
            argv.append(a)
    hook_mode = len(argv) == 1
    try:
        # the check quotes the lines it reads: a base is read only from the task work root (this invocation may be auto-approved)
        if base_path is not None and not (inside_work_root(base_path) and os.path.isfile(base_path)):
            raise PermissionError(f"--base must name a file inside the task work root, not {base_path}")
        base = None
        if base_path is not None:
            with open(base_path, encoding="utf-8", newline="") as f:
                base = f.read()
        inp, _, proposal_file = load(argv)
        base_claims = None
        if isinstance(inp, dict) and inp.get("kind") == "small_edit":
            if base is None:
                base = base_beside(proposal_file)
            base_claims = base_claims_beside(proposal_file)
        problems, warnings = check(inp, base=base, page_domain=domain, base_claims=base_claims)
    except Exception as e:
        problems = [f"pre-flight could not check this proposal ({type(e).__name__}: {e}); fix the proposal shape"]
        warnings = []
    if hook_mode:
        # Loading failures must produce a denial too; silent hook failures may allow a call.
        if problems:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                              "permissionDecisionReason": "scio: fix before proposing — " + "; ".join(problems[:8])}}))
        elif warnings:   # context only — no decision: whether the call is silent is the trust gate's (auto-approve.py) and the harness's call
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                              "additionalContext": "scio pre-flight warnings (not blocking): " + "; ".join(warnings[:6])}}))
        sys.exit(0)
    for p in problems:
        print(f"ERROR   {p}")
    for w in warnings:
        print(f"WARNING {w}")
    if not problems and not warnings:
        print("ok: no problems found")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
