#!/usr/bin/env python3
"""Regression test for fetch.py's content extraction (security.md §3's "text read per fetched page" budget):
    python3 tests/test-extraction.py
Exercises the pure functions directly (no network — guard-fetch.py refuses every address a local test server
could bind to, by design, so this never goes through fetch()/get_once()). Covers the token-efficiency fix: dropping
structural boilerplate (nav/header/footer/aside/form/dialog) and cookie/consent/breadcrumb containers by a real
open-tag stack rather than a truncate-then-strip regex, without over-stripping legitimately named containers, and
applying the --max-bytes budget to the extracted text instead of to the raw download. Exit 0 when every case holds."""
import importlib.util, os, sys

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
    return fetch._stdlib_extract(html)


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

# --- cookie/consent/gdpr/breadcrumb: dropped by whole-token class/id match -------------------------------------
banner = """
<html><body>
<div class="cookie-banner"><p>We use cookies. Accept all.</p></div>
<div id="gdpr-consent-notice"><p>Manage your privacy choices.</p></div>
<div class="breadcrumbs"><a href="/">Home</a> &gt; <a href="/cat">Category</a></div>
<p>The paragraph that matters.</p>
</body></html>
"""
out = extract(banner)
expect("We use cookies" not in out, "cookie-banner class is dropped")
expect("Manage your privacy choices" not in out, "gdpr-consent-notice id is dropped")
expect("Category" not in out, "breadcrumbs class is dropped")
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
# 'cookies-policy-explainer' does contain the boundary word 'cookies' as a whole token by design (security.md's
# conservative side: an occasional false positive here is cheaper than leaving real cookie banners in every page)
expect("An article explaining cookie law" not in out, "documented trade-off: 'cookies' as a whole token still matches, even mid-compound")

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

print(f"\n{len(failures)} failure(s)" if failures else "\nall extraction checks passed")
sys.exit(1 if failures else 0)
