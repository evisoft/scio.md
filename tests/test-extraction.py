#!/usr/bin/env python3
"""Regression test for fetch.py's content extraction (security.md §3's "text read per fetched page" budget):
    python3 tests/test-extraction.py
Exercises the pure functions directly (no network — guard-fetch.py refuses every address a local test server
could bind to, by design, so this never goes through fetch()/get_once()). Covers the token-efficiency fix: dropping
structural boilerplate (nav/footer/form/dialog) and, outside <article>/<main>, header/aside and cookie/consent/
breadcrumb containers, by a real open-tag stack rather than a truncate-then-strip regex; retaining header/aside
nested inside the identified article (titles, bylines, callouts); applying the --max-bytes budget (actual UTF-8
bytes, not Unicode code points) to the extracted text instead of to the raw download; and refusing binary content
types outright. Exit 0 when every case holds."""
import contextlib, importlib.util, io, os, subprocess, sys

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
    text, ok = fetch._stdlib_extract(html)
    return text


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
text, method = fetch.to_text(raw, "text/html")
expect("real article sentence survives a huge header" in text, "extraction reaches content past 300 KB of dropped header (the ordering-fix regression case)")
expect(len(text) < 1000, "the header contributes ~0 extracted chars regardless of its raw size")
expect(method in ("trafilatura", "stdlib"), "to_text reports which extractor ran")

# --- non-HTML content is passed through, not run through the extractor -----------------------------------------
plain, plain_method = fetch.to_text(b"plain text, no markup here", "text/plain")
expect(plain == "plain text, no markup here", "plain text is untouched")
expect(plain_method == "text", "non-HTML content is reported as method='text', not run through either extractor")

# --- header/aside nested in <article>/<main> carry exactly what a researcher needs: retained ---------------------
article_meta = """
<html><body>
<div class="site-header"><nav>Home About Contact</nav></div>
<article>
  <header><h1>The Real Headline</h1><p class="byline">By Jane Researcher, 2026-01-01</p></header>
  <p>The body text of the article.</p>
  <aside><p>Editor's note: a definition box worth keeping.</p></aside>
</article>
</body></html>
"""
out = extract(article_meta)
expect("The Real Headline" in out, "an <article><header> title survives (was unconditionally dropped before this fix)")
expect("By Jane Researcher" in out, "a byline inside an article header survives")
expect("The body text of the article" in out, "ordinary article body text still survives")
expect("Editor's note: a definition box worth keeping" in out, "an <aside> nested inside <article> survives (was unconditionally dropped before this fix)")
expect("Home About Contact" not in out, "a site-level header outside <article>/<main> is still dropped")

# --- a cookie/consent/breadcrumb container is boilerplate even spelled as <aside>/<header>, even inside <article> ---
# (the header/aside ancestor rule above must not shadow the boundary-word check for these two tags specifically)
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
expect("Accept cookies to continue reading" not in out, "an <aside class='cookie-banner'> nested inside <article> is still dropped, not kept by the header/aside ancestor rule")
expect("Real Title" in out and "Real body text" in out, "the article's own title and body survive alongside the fix")

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

# --- binary content types are recognized and refused rather than decoded as text ---------------------------------
expect("image/jpeg".startswith(fetch.BINARY_CONTENT_TYPES), "image/jpeg is recognized as a binary content type")
expect("application/pdf".startswith(fetch.BINARY_CONTENT_TYPES), "application/pdf is recognized as a binary content type")
expect(not "text/html".startswith(fetch.BINARY_CONTENT_TYPES), "text/html is not treated as binary")
expect(not "application/xhtml+xml".startswith(fetch.BINARY_CONTENT_TYPES), "application/xhtml+xml is not treated as binary")

# --- main() end to end: diagnostics header, binary refusal, low-content warning (fetch() monkeypatched, no network)
out_main = run_main(["https://example.com/article"], "<html><body><article><p>Hello world.</p></article></body></html>")
expect("bytes via stdlib" in out_main and "Hello world." in out_main, "main() reports the extraction method and still prints the extracted text")
out_bin = run_main(["https://example.com/photo.jpg"], "ignored", ctype="image/jpeg")
expect("binary content type, not decoded as text" in out_bin, "main() refuses a binary content type before decoding or scanning it")
sparse_page = "<html><body><header>" + ("x " * 4000) + "</header><nav>" + ("y " * 4000) + "</nav></body></html>"
out_sparse = run_main(["https://example.com/js-app"], sparse_page)
expect("may need JavaScript to render" in out_sparse, "main() flags a substantial page that extracted almost nothing, instead of returning an unexplained near-empty result")

# --- raw truncation gets its own prominent warning, distinct from an ordinary budget truncation --------------------
out_raw_trunc = run_main(["https://example.com/big-page"], "<html><body><article><p>Some content.</p></article></body></html>", raw_truncated=True)
expect("WARNING" in out_raw_trunc and "may be incomplete" in out_raw_trunc, "a raw download cap triggers a standalone, stronger warning than a plain budget truncation")
out_no_raw_trunc = run_main(["https://example.com/small-page"], "<html><body><article><p>Some content.</p></article></body></html>")
expect("WARNING" not in out_no_raw_trunc, "no raw-truncation warning appears when the raw download was not capped")

# --- SCIO_EXTRACTOR pins the extractor for fleets that want identical behaviour everywhere ------------------------
try:
    import trafilatura as _installed_trafilatura   # noqa: F401
    has_trafilatura = True
except ImportError:
    has_trafilatura = False
env = dict(os.environ, SCIO_EXTRACTOR="trafilatura")
r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "fetch.py")], capture_output=True, text=True, env=env)
if has_trafilatura:
    expect(r.returncode != 1 or "not installed" not in r.stdout, "SCIO_EXTRACTOR=trafilatura runs normally when the package is importable")
else:
    expect(r.returncode == 1 and "SCIO_EXTRACTOR=trafilatura" in r.stdout and "not installed" in r.stdout,
           "SCIO_EXTRACTOR=trafilatura refuses to run when the package is missing, instead of silently falling back to stdlib")

# --- a package present on disk but failing to import (a broken transitive dependency) is reported distinctly from
# "not installed" — find_spec() sees it as present, so the failure must come from the import itself
import tempfile as _tf
fake_pkg_dir = _tf.mkdtemp()
os.makedirs(os.path.join(fake_pkg_dir, "trafilatura"))
with open(os.path.join(fake_pkg_dir, "trafilatura", "__init__.py"), "w") as f:
    f.write("raise ImportError(\"No module named 'lxml.etree'\")\n")
broken_env = dict(os.environ, SCIO_EXTRACTOR="trafilatura", PYTHONPATH=fake_pkg_dir + os.pathsep + os.environ.get("PYTHONPATH", ""))
r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "fetch.py")], capture_output=True, text=True, env=broken_env)
expect(r.returncode == 1 and "failed to import" in r.stdout and "not installed" not in r.stdout,
       "a present-but-broken trafilatura install is reported as 'failed to import', distinct from 'not installed'")
expect("ImportError" in r.stdout, "the broken-import diagnostic names the actual exception type")


def extractor_mode(value):
    e = dict(os.environ)
    if value is None:
        e.pop("SCIO_EXTRACTOR", None)
    else:
        e["SCIO_EXTRACTOR"] = value
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "fetch.py")], capture_output=True, text=True, env=e)
    return r.returncode, r.stdout


code, out = extractor_mode("stdlib")
expect(code == 2 and "must be one of" not in out, "SCIO_EXTRACTOR=stdlib is a valid mode (prints the CLI usage doc for no URL, not a mode error)")
code, out = extractor_mode(" StdLib ")
expect(code == 2 and "must be one of" not in out, "SCIO_EXTRACTOR is trimmed and lower-cased (' StdLib ' is accepted)")
code, out = extractor_mode("")
expect(code == 2 and "must be one of" not in out, "an empty SCIO_EXTRACTOR falls back to the 'auto' default rather than erroring")
code, out = extractor_mode("trafiltura")   # the exact typo from the review this regression test is named for
expect(code == 2 and "must be one of" in out, "an invalid SCIO_EXTRACTOR value (a typo) fails loudly instead of silently behaving as stdlib")

# --- an <article><footer> carries evidence (author bio, correction notice, licence line); a page footer is chrome --
footer_page = """
<html><body>
<article>
<p>Body text.</p>
<footer><p>Corrections: an earlier version misstated the date.</p></footer>
</article>
<footer><p>Site-wide legal boilerplate.</p></footer>
</body></html>
"""
out = extract(footer_page)
expect("Corrections: an earlier version misstated the date" in out, "a <footer> nested inside <article> survives (was unconditionally dropped before this fix)")
expect("Site-wide legal boilerplate" not in out, "a page-level <footer> outside <article>/<main> is still dropped")

# --- meaningful <img alt> text is kept and labelled, not silently discarded (security.md: alt text is scanned like prose)
alt_page = '<html><body><article><p>Before.</p><img src="chart.png" alt="Revenue rose 12% year over year"><p>After.</p></article></body></html>'
out = extract(alt_page)
expect("[image description: Revenue rose 12% year over year]" in out, "meaningful alt text is kept, labelled as an image description")
expect("Before." in out and "After." in out, "surrounding text is unaffected by the alt-text capture")
empty_alt = '<html><body><article><img src="spacer.gif" alt=""><p>Text.</p></article></body></html>'
expect("[image description:" not in extract(empty_alt), "an empty alt attribute produces no image-description line")
whitespace_alt = '<html><body><article><img src="a.png" alt="  padded   \n  text  "></article></body></html>'
expect("[image description: padded text]" in extract(whitespace_alt), "embedded whitespace in alt text is collapsed before it is emitted")
presentation_alt = '<html><body><article><img src="deco.png" alt="decorative flourish" role="presentation"></article></body></html>'
expect("decorative flourish" not in extract(presentation_alt), "role='presentation' images are treated as decorative, not a caption, even with alt text present")

# --- a single huge alt value cannot displace the article; many small ones cannot add up to displace it either -----
huge_alt = '<html><body><article><p>Real.</p><img src="a.png" alt="' + ("x" * 5000) + '"></article></body></html>'
huge_out = extract(huge_alt)
expect(huge_out.count("x") <= fetch.MAX_ALT_TEXT_CHARS, "a single oversized alt value is capped, not emitted in full")
expect("Real." in huge_out, "the article text is unaffected by a capped oversized alt value")
many_alts = "".join(f'<img src="a{i}.png" alt="alt number {i} padding padding padding padding">' for i in range(50))
many_html = f'<html><body><article><p>Start.</p>{many_alts}<p>End.</p></article></body></html>'
many_parser = fetch._Extractor()
many_parser.feed(many_html)
many_parser.close()
many_out = "".join(many_parser.chunks)
expect(many_parser.alt_budget <= 0, "50 images each well under the per-image cap still exhaust the aggregate alt-text budget")
expect(sum(len(c) for c in many_parser.chunks if c.startswith("\n[image description: ")) < fetch.MAX_TOTAL_ALT_TEXT_CHARS * 2,
       "the alt-text content actually emitted (labels aside) stays within a small multiple of the aggregate cap, not unbounded")
expect("Start." in many_out and "End." in many_out, "article text before and after a run of images both survive the aggregate alt-text cap")

# --- expanded binary denylist covers common archive/executable types; +xml/+json vendor types are still textual ---
for binary_type in ("application/x-rar-compressed", "application/x-7z-compressed", "application/gzip", "application/x-executable"):
    expect(binary_type.startswith(fetch.BINARY_CONTENT_TYPES), f"{binary_type} is recognized as a binary content type")
expect("application/vnd.api+json".startswith(fetch.BINARY_CONTENT_TYPES) and "application/vnd.api+json".endswith(fetch.TEXTUAL_VENDOR_SUFFIXES),
       "a +json vendor type matches the vnd. prefix but also the textual-suffix exception (main() combines both)")

# --- content-type comparison is case-insensitive (HTTP media types are case-insensitive per the spec) -------------
mixed_case, mixed_method = fetch.to_text(b"<html><body><article><p>Cased content type.</p></article></body></html>", "Text/HTML; Charset=UTF-8")
expect("Cased content type" in mixed_case, "a mixed-case Content-Type (Text/HTML) still triggers extraction, not just the body-sniff fallback")

# --- a forced trafilatura exception falls back to stdlib and reports the exception type, without a crash ----------
class _BoomExtractor:
    def extract(self, *a, **kw):
        raise ValueError("synthetic failure for the test")


real_trafilatura = fetch._trafilatura
fetch._trafilatura = _BoomExtractor()
try:
    boom_text, boom_method = fetch.extract_html("<html><body><article><p>Still extracted via stdlib.</p></article></body></html>")
finally:
    fetch._trafilatura = real_trafilatura
expect("Still extracted via stdlib" in boom_text, "a trafilatura exception still falls back to a usable stdlib extraction")
expect(boom_method == "stdlib (trafilatura: ValueError)", "the exception type is reported, not swallowed and not its message")

# --- scio_local.py's t_fetch requests a much smaller budget by default, still capped at the 200 KB ceiling --------
SERVER = os.path.join(os.path.dirname(HERE), "skills", "scio", "server")
local_spec = importlib.util.spec_from_file_location("scio_local", os.path.join(SERVER, "scio_local.py"))
scio_local = importlib.util.module_from_spec(local_spec)
sys.path.insert(0, SERVER)
local_spec.loader.exec_module(scio_local)

expect(scio_local.DEFAULT_FETCH_BYTES == 20_000, "the MCP layer's default fetch budget is 20 KB, well under the 200 KB ceiling")
expect(scio_local.MAX_FETCH_BYTES == 200_000, "the MCP layer's fetch ceiling still matches security.md §3's 200 KB")

captured_args = {}


def fake_run(script, args=(), **kw):
    captured_args["args"] = args
    return 0, "ok"


real_run = scio_local.run
scio_local.run = fake_run
try:
    scio_local.t_fetch({"url": "https://example.com"})
    expect(captured_args["args"] == ["https://example.com", "--max-bytes", "20000"], "no max_bytes given: t_fetch requests the 20 KB default, not the full 200 KB ceiling")
    scio_local.t_fetch({"url": "https://example.com", "max_bytes": 500_000})
    expect(captured_args["args"] == ["https://example.com", "--max-bytes", "200000"], "an oversized max_bytes request is still clamped to the 200 KB ceiling")
    scio_local.t_fetch({"url": "https://example.com", "max_bytes": 50_000})
    expect(captured_args["args"] == ["https://example.com", "--max-bytes", "50000"], "an explicit in-range max_bytes is passed through unchanged")
    scio_local.t_fetch({"url": "https://example.com", "max_bytes": 0})
    expect(captured_args["args"] == ["https://example.com", "--max-bytes", "1"], "an explicit max_bytes of 0 is clamped to the floor of 1, not silently swapped for the unrelated 20 KB default")
    scio_local.t_fetch({"url": "https://example.com", "max_bytes": -50})
    expect(captured_args["args"] == ["https://example.com", "--max-bytes", "1"], "a negative max_bytes is clamped to the floor of 1")
    scio_local.t_fetch({"url": "https://example.com", "max_bytes": 1})
    expect(captured_args["args"] == ["https://example.com", "--max-bytes", "1"], "the minimum boundary value 1 is passed through unchanged")
    scio_local.t_fetch({"url": "https://example.com", "max_bytes": 200_000})
    expect(captured_args["args"] == ["https://example.com", "--max-bytes", "200000"], "the maximum boundary value 200000 is passed through unchanged")
finally:
    scio_local.run = real_run

# --- camelCase compounds (cookieBanner, gdprNotice) are boundary-word matches too, not just kebab/snake case ------
for compound in ("cookieBanner", "gdprNotice", "cookieConsent", "GDPRNotice", "consentBox"):
    expect(fetch._is_boundary_blob(compound), f"class='{compound}' (camelCase) is recognized as a boundary word")
expect(not fetch._is_boundary_blob("commentary"), "camelCase splitting does not turn 'commentary' into a false positive")
expect(not fetch._is_boundary_blob("menuRecipeBody"), "an unrelated camelCase compound is still not a boundary-word match")

# --- writing --out to an existing directory is refused cleanly, not an unhandled IsADirectoryError crash ----------
import tempfile
work_dir = tempfile.mkdtemp()
target_dir = os.path.join(work_dir, "some_dir")
os.makedirs(target_dir)
real_environ = dict(os.environ)
os.environ["SCIO_WORK_DIR"] = work_dir
try:
    try:
        out_dir_result = run_main(["https://example.com/article", "--out", target_dir],
                                   "<html><body><article><p>Text.</p></article></body></html>")
        crashed = False
    except IsADirectoryError:
        crashed = True
        out_dir_result = ""
    expect(not crashed, "writing --out to an existing directory does not crash with an unhandled IsADirectoryError")
    expect("is a directory" in out_dir_result, "writing --out to an existing directory prints a clean refusal message")
finally:
    os.environ.clear()
    os.environ.update(real_environ)

print(f"\n{len(failures)} failure(s)" if failures else "\nall extraction checks passed")
sys.exit(1 if failures else 0)
