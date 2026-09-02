#!/usr/bin/env python3
"""Regression test for fetch.py's content extraction (security.md §3's raw-download cap and extracted-text budget):
    python3 tests/test-extraction.py
Exercises the pure functions directly (no network — guard-fetch.py refuses every address a local test server
could bind to, by design, so this never goes through fetch()/get_once()). Covers the token-efficiency fix: dropping
structural boilerplate (nav/form/dialog) and, outside <article>/<main>, header/footer/aside and cookie/consent/
breadcrumb containers, by a real open-tag stack rather than a truncate-then-strip regex; retaining header/footer/
aside nested inside an <article>/<main> ancestor (titles, bylines, correction notices, callouts); applying the
--max-bytes budget (actual UTF-8 bytes, not Unicode code points) to the extracted text instead of to the raw
download. Exit 0 when every case holds."""
import contextlib, importlib.util, io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "scio", "scripts")
sys.path.insert(0, SCRIPTS)
spec = importlib.util.spec_from_file_location("fetch", os.path.join(SCRIPTS, "fetch.py"))
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)

failures = []


def expect(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def extract(html):
    return fetch.extract_html(html)


def run_main(argv, page_html, ctype="text/html", raw_truncated=False):
    """Runs fetch.main() with fetch() monkeypatched to return page_html without touching the network — guard-fetch.py
    would refuse any address a local test server could bind to anyway, so this is the only way to exercise main()."""
    real_fetch, real_argv = fetch.fetch, sys.argv
    fetch.fetch = lambda url, cap=None: ((page_html.encode(), ctype, raw_truncated), None, url)
    sys.argv = ["fetch.py"] + argv
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            try:
                fetch.main()
            except SystemExit:
                pass
    finally:
        fetch.fetch, sys.argv = real_fetch, real_argv
    return buf.getvalue()


# --- structural boilerplate: dropped wherever it sits, however deep --------------------------------------------
page = """
<html><body>
<header><div><div><a href="/">Home</a><a href="/about">About</a></div></div></header>
<nav><ul><li><a href="/x">X</a></li><li><a href="/y">Y</a></li></ul></nav>
<article><p>The article's real sentence about the subject.</p></article>
<aside><div>Sponsored: buy this thing now.</div></aside>
<footer><div>Copyright 2026. <a href="/privacy">Privacy</a></div></footer>
</body></html>
"""
out = extract(page)
expect("real sentence about the subject" in out, "content inside <article> survives nav/header/footer/aside")
expect("Home" not in out and "About" not in out, "header (nested divs) is dropped as one subtree")
expect("Sponsored" not in out, "aside is dropped")
expect("Copyright" not in out, "footer is dropped")

# --- nested boilerplate: a regex truncates at the first </div>; the tag-stack must not ------------------------
nested = """
<html><body>
<div class="cookie-consent"><div><div><p>widget one</p></div><div><p>widget two</p></div></div></div>
<p>Actual article text that must survive.</p>
</body></html>
"""
out = extract(nested)
expect("widget one" not in out and "widget two" not in out, "a cookie-consent div containing further nested divs is dropped whole")
expect("Actual article text that must survive" in out, "content after a nested boilerplate div is still captured (skip_root correctly clears)")

# --- cookie/consent/gdpr/breadcrumb: dropped by whole-token class/id match, including camelCase -----------------
banner = """
<html><body>
<div class="cookie-banner"><p>We use cookies. Accept all.</p></div>
<div id="gdpr-consent-notice"><p>Manage your privacy choices.</p></div>
<div class="breadcrumbs"><a href="/">Home</a> &gt; <a href="/cat">Category</a></div>
<div class="cookieBanner"><p>camelCase variant.</p></div>
<p>The paragraph that matters.</p>
</body></html>
"""
out = extract(banner)
expect("We use cookies" not in out, "cookie-banner class is dropped")
expect("Manage your privacy choices" not in out, "gdpr-consent-notice id is dropped")
expect("Category" not in out, "breadcrumbs class is dropped")
expect("camelCase variant" not in out, "a camelCase compound (cookieBanner) is recognized as a boundary word too")
expect("The paragraph that matters" in out, "real content after the banners survives")

# --- false positives: names that merely contain a boundary word as a substring must NOT be dropped -------------
falsepos = """
<html><body>
<div class="commentary"><p>An editorial commentary paragraph, not a comment thread.</p></div>
<div id="menu-recipe-body"><p>Step one: preheat the oven.</p></div>
<div class="article-share-quotes"><p>A pull quote worth keeping.</p></div>
<div class="cookies-policy-explainer"><p>An article explaining cookie law, not a banner.</p></div>
</body></html>
"""
out = extract(falsepos)
expect("editorial commentary paragraph" in out, "class='commentary' is not treated as a cookie/consent boundary word")
expect("preheat the oven" in out, "id='menu-recipe-body' is not treated as nav")
expect("pull quote worth keeping" in out, "class='article-share-quotes' is not treated as boilerplate")
# 'cookies-policy-explainer' does contain the boundary word 'cookies' as a whole token by design (the conservative
# side: an occasional false positive here is cheaper than leaving real cookie banners in every page)
expect("An article explaining cookie law" not in out, "documented trade-off: 'cookies' as a whole token still matches, even mid-compound")

# --- header/footer/aside nested in <article>/<main> carry exactly what a researcher needs: retained -------------
article_meta = """
<html><body>
<div class="site-header"><nav>Home About Contact</nav></div>
<article>
  <header><h1>The Real Headline</h1><p class="byline">By Jane Researcher, 2026-01-01</p></header>
  <p>The body text of the article.</p>
  <aside><p>Editor's note: a definition box worth keeping.</p></aside>
  <footer><p>Corrections: an earlier version misstated the date.</p></footer>
</article>
<footer><p>Site-wide legal boilerplate.</p></footer>
</body></html>
"""
out = extract(article_meta)
expect("The Real Headline" in out, "an <article><header> title survives")
expect("By Jane Researcher" in out, "a byline inside an article header survives")
expect("The body text of the article" in out, "ordinary article body text still survives")
expect("Editor's note: a definition box worth keeping" in out, "an <aside> nested inside <article> survives")
expect("Corrections: an earlier version misstated the date" in out, "a <footer> nested inside <article> survives")
expect("Home About Contact" not in out, "a site-level header outside <article>/<main> is still dropped")
expect("Site-wide legal boilerplate" not in out, "a page-level footer outside <article>/<main> is still dropped")

# --- a cookie/consent/breadcrumb container is boilerplate even inside <article>, even spelled as header/footer/aside
cookie_in_article = """
<html><body>
<article>
<header><h1>Real Title</h1></header>
<p>Real body text.</p>
<aside class="cookie-banner"><p>Accept cookies to continue reading.</p></aside>
</article>
</body></html>
"""
out = extract(cookie_in_article)
expect("Accept cookies to continue reading" not in out, "an <aside class='cookie-banner'> nested inside <article> is still dropped, not kept by the header/footer/aside ancestor rule")
expect("Real Title" in out and "Real body text" in out, "the article's own title and body survive alongside the fix")

# --- ordering fix: budget applies to extracted text, not to raw bytes spent on boilerplate ---------------------
big_header = "<header>" + ("nav link " * 40_000) + "</header>"   # ~360 KB of raw markup, all of it dropped
page2 = f"<html><body>{big_header}<article><p>The real article sentence survives a huge header.</p></article></body></html>"
raw = page2.encode()
expect(len(raw) > 300_000, "sanity: the synthetic header is larger than the 200 KB fetch budget")
text = fetch.to_text(raw, "text/html")
expect("real article sentence survives a huge header" in text, "extraction reaches content past 300 KB of dropped header (the ordering-fix regression case)")
expect(len(text) < 1000, "the header contributes ~0 extracted chars regardless of its raw size")

# --- non-HTML content is passed through, not run through the extractor -----------------------------------------
expect(fetch.to_text(b"plain text, no markup here", "text/plain") == "plain text, no markup here", "plain text is untouched")
mixed_case = fetch.to_text(b"<html><body><article><p>Cased content type.</p></article></body></html>", "Text/HTML; Charset=UTF-8")
expect("Cased content type" in mixed_case, "a mixed-case Content-Type (Text/HTML) still triggers extraction, not just the body-sniff fallback")

# --- byte-accurate truncation: --max-bytes means UTF-8 bytes, not Python's len() (Unicode code points) -----------
# each "中" is 3 UTF-8 bytes but 1 code point: a char-based cap would let 3x the promised bytes through
cjk = "中" * 100
capped, was_truncated, returned = fetch.truncate_utf8(cjk, 30)
expect(was_truncated, "a 300-byte string is truncated against a 30-byte budget")
expect(returned <= 30, "truncate_utf8 never returns more than max_bytes of UTF-8-encoded text")
expect(len(capped.encode("utf-8")) == returned, "the reported byte count matches the actual encoded length")
expect("�" not in capped, "a multi-byte character is never split into a replacement character")
untouched, was_truncated2, returned2 = fetch.truncate_utf8("short", 1000)
expect(not was_truncated2 and untouched == "short" and returned2 == 5, "text under the budget is returned unchanged")
paragraphs = "First paragraph, fairly short.\n\nSecond paragraph that runs long enough to cross the byte budget here."
cut, cut_truncated, _ = fetch.truncate_utf8(paragraphs, 45)
expect(cut_truncated and cut == "First paragraph, fairly short.", "a truncation is pulled back to the preceding paragraph break instead of landing mid-sentence")

# --- main() end to end: diagnostics, raw-truncation note, ordinary case (fetch() monkeypatched, no network) -----
out_main = run_main(["https://example.com/article"], "<html><body><article><p>Hello world.</p></article></body></html>")
expect("bytes extracted" in out_main and "Hello world." in out_main, "main() reports extraction diagnostics and still prints the extracted text")
out_raw_trunc = run_main(["https://example.com/big-page"], "<html><body><article><p>Some content.</p></article></body></html>", raw_truncated=True)
expect("raw download capped" in out_raw_trunc and "may be incomplete" in out_raw_trunc, "a raw download cap is reported distinctly and more strongly than an ordinary budget truncation")
out_no_raw_trunc = run_main(["https://example.com/small-page"], "<html><body><article><p>Some content.</p></article></body></html>")
expect("raw download capped" not in out_no_raw_trunc, "no raw-truncation note appears when the raw download was not capped")

print(f"\n{len(failures)} failure(s)" if failures else "\nall extraction checks passed")
sys.exit(1 if failures else 0)
