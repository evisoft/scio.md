#!/usr/bin/env python3
"""Flag instruction-injection and steering patterns in text you are about to read at length — panel material,
discussions, fetched pages, proposals. Crude on purpose: it catches the common cases so your attention goes to the
subtle ones. Never a reason to comply with anything; a hit is evidence about the text's author (security.md §4).

  scan-injection.py <file|-> [--json]      text (or JSON: scanned recursively over every string) → findings
  exit 0 = nothing found, 1 = findings

Used by check-claims.py on proposal bodies, quotes and claim URLs, and by the review/translate workflows before reading."""
import ipaddress, json, os, re, sys
from importlib import import_module
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_guard = import_module("guard-fetch")   # one address policy for both (guard-fetch owns it)
_is_private_host = _guard.is_private_host

PATTERNS = [
    # an address to the reader ("Note to reviewers:", "Dear AI", "To the agents reading this"); a bare "to" only opens a
    # sentence, so "fitted to the model" and "sold to agents" stay prose
    ("addressed_to_agent", re.compile(r"(?:\b(?:dear|note to|attention|instructions? for|message to|hello|hi|hey)[:,]?\s+|(?:^|[.!?:;]\s*|\n\s*)to\s+)(?:the\s+|all\s+|any\s+)?(?:ai|agent|agents|reviewer|reviewers|translator|model|assistant|llm)s?\b", re.I)),
    # "as an AI" as self-reference ("as an AI, I…", "as an AI language model"); "as an AI researcher" is a career
    ("harness_vocabulary", re.compile(r"\b(system prompt|developer message|(?:ignore|disregard|forget) (?:all |the |any |your )?(?:previous|prior|above|earlier) (?:instructions?|rules?|guidance)|tool[_ ]call|function[_ ]call|jailbreak|you are (now|an?) (ai|assistant|model)|as an ai(?:\s+(?:language\s+)?(?:model|assistant)\b|(?=\s*[,.;:!?)]|\s*$|\s+i\b))|end of (system|instructions?))\b", re.I)),
    ("fake_role_marker", re.compile(r"(^|\n)\s*(?:[#>*_]+\s*)?(system|assistant|user|developer|tool|human|reviewers?|to reviewers)\s*:\s", re.I)),
    ("skip_verification", re.compile(r"\b(no need to (open|check|verify|read)|already (verified|checked|reviewed)(?=\s*[,.;:!)]|\s+(?:by|and|so|no)\b|\s*$)|(?:this|it|he|she|i) (?:is|am) a trusted (author|source)|from a trusted (author|source)\s*[,.;:]|skip (the )?(verification|sources|check))\b", re.I)),
    ("verdict_steering", re.compile(r"\b(you (must|should|have to) (approve|reject|accept)|please approve|(?<!to )approve this(?! (?:measure|bill|plan|budget|law|proposal of|request of|motion))|mark (it|this) (as )?supported|(approve|accept|reject) (it |this |them |everything |all )?(without|before) (opening|reading|checking|verifying)|(label|mark) (every|all|each) claims? (as )?(supported|unsupported|disputed))\b", re.I)),
    # a request for a credential, not the words "secret" and "password" wherever they occur (a secret ballot, a password policy)
    ("exfiltration", re.compile(r"\b(api[_ ]?key|bearer token|secret key|access token|auth(?:orization)? token|(?:your|its|the agent'?s?|operator'?s?)\s+(?:secret|password|key|token|credentials?)|(?:paste|send|include|reveal|share|post|print|append|attach|embed|leak|copy)\s+(?:the\s+|your\s+|an?\s+)?(?:secret|password|key|token|credential)s?|\.config/scio|SCIO_API_KEY|operator'?s? email)\b", re.I)),
    # a key-shaped token; a plain hex run (a git commit, a sha256 in media:<sha>.<ext>) is a hash, not a key
    ("key_shaped", re.compile(r"\b(sk|scio|ak)_[A-Za-z0-9]{16,}\b|\b(?![0-9a-f]+\b)[A-Za-z0-9+/]{40,}={0,2}\b")),
    ("script_or_markup", re.compile(r"<script\b|javascript:|onerror\s*=|<iframe\b", re.I)),
    ("urgency_flattery", re.compile(r"\b(urgent(ly)?|immediately|before (your|the) (assignments|deadline)|you are (the best|very smart|highly ranked))\b", re.I)),
]
ENCODING = [
    ("zero_width_chars", re.compile(r"[\u00ad\u034f\u180e\u200b\u200c\u200d\u2060-\u2064\ufeff]")),
    ("bidi_controls", re.compile(r"[\u202a-\u202e\u2066-\u2069]")),
    ("escaped_text", re.compile(r"(\\u[0-9a-fA-F]{4}){4,}|(&#x?[0-9a-fA-F]+;){4,}|(%[0-9a-fA-F]{2}){8,}")),
    # a command line, not a sentence that starts with the name of a program ("Python was created…", "Bash is a shell"):
    # the word must be followed by something a shell would take — a flag, a path, a URL, a script, a quote, a pipe
    ("shell_command", re.compile(r"(^|\n|`|:\s+|\$\s+|[;&|]\s*)\s*(?:(?:curl|wget|bash|sh|python3?)\s+(?:[-/~.$\x22\x27<|(]|https?://|\S+\.[a-z]{2,4}(?:/|\s|$))|scio-as\s+[A-Za-z0-9_-]+\s+\S|export\s+SCIO_API_KEY)[^\n`]{0,120}", re.I)),
]


# a URL in free text: the scheme is short and starts at a word boundary, so a long alphanumeric run (base64, minified
# code) is not rescanned from every position — that made a 200 KB page take minutes
URL_RE = re.compile(r"https?://[^\s\)\]\"'>]{1,2000}|\b[a-z][a-z0-9+.-]{1,15}://[^\s\)\]\"'>]{1,2000}", re.I)


def url_findings(url):
    out = []
    try:
        u = urlparse(url)
    except Exception:
        return [("bad_url", url)]
    if u.scheme and u.scheme not in ("https", "http"):
        out.append(("non_http_scheme", url))
    host = u.hostname or ""
    if host and not host.isascii():
        out.append(("non_ascii_host", url))
    if any(label.startswith("xn--") for label in host.split(".")):
        out.append(("punycode_host", url))
    if _is_private_host(host):
        out.append(("private_host", url))
    if _guard.NUMERIC_HOST.fullmatch(host):   # an address, not a name: private, or written in a form (decimal, hex) meant to slip past a reader
        try:
            if _guard.bad_ip(host.strip("[]")):
                out.append(("private_ip", url))
        except ValueError:
            out.append(("private_ip", url))
    if u.query and re.search(r"(key|token|secret|auth|session|api)=", u.query, re.I):
        out.append(("identifier_in_query", url))
    return out


def scan_text(text, where="text"):
    found = []
    for name, rx in PATTERNS:
        for m in rx.finditer(text):
            s = max(0, m.start() - 40); e = min(len(text), m.end() + 40)
            found.append({"pattern": name, "where": where, "excerpt": text[s:e].replace("\n", " ")})
            if len([f for f in found if f["pattern"] == name]) >= 3:
                break
    for name, rx in ENCODING:
        # percent-escapes inside a URL are how a non-Latin address is written (a Japanese or Chinese source), not a trick
        m = rx.search(URL_RE.sub(" ", text) if name == "escaped_text" else text)
        if m:
            s = max(0, m.start() - 30); e = min(len(text), m.end() + 30)
            found.append({"pattern": name, "where": where, "excerpt": text[s:e].replace("\n", " ")})
    for url in URL_RE.findall(text):
        for name, u in url_findings(url):
            found.append({"pattern": name, "where": where, "excerpt": u[:120]})
    return found


def scan_json(node, path="$"):
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            found += scan_json(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += scan_json(v, f"{path}[{i}]")
    elif isinstance(node, str):
        found += scan_text(node, path)
        if re.search(r"(source_url|second_source_url|url)$", path):
            found += [{"pattern": n, "where": path, "excerpt": u[:120]} for n, u in url_findings(node)]
    return found


def dedupe(found):
    seen, out = set(), []
    for f in found:
        k = (f["pattern"], f["where"], f["excerpt"])
        if k not in seen:
            seen.add(k); out.append(f)
    return out


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__.strip()); sys.exit(2)
    for stream in (sys.stdin, sys.stdout):   # the text is UTF-8 whatever the locale (Windows: cp1252 otherwise)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    raw = sys.stdin.read() if a[0] == "-" else open(a[0], encoding="utf-8", errors="replace").read()
    try:
        found = dedupe(scan_json(json.loads(raw)))
    except ValueError:
        found = dedupe(scan_text(raw))
    if "--json" in a:
        print(json.dumps(found, ensure_ascii=False, indent=1))
    else:
        for f in found:
            print(f"{f['pattern']:22} {f['where']}: …{f['excerpt']}…")
        if not found:
            print("ok: no injection patterns found")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
