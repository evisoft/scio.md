#!/usr/bin/env python3
"""Write, or check, the three copies of the platform's tool contract the plugin carries — all from one source.

  sync-contract.py [SOURCE]           write them (scripts/release.sh does, at every release)
  sync-contract.py --check [SOURCE]   write nothing; exit 1 naming each copy that differs from what SOURCE generates

SOURCE is the deployed contract, `https://scio.md/v1/tools.json` (the platform serves the file its image was built
with), or a path to a copy of it. The three copies:

  skills/scio/references/tools.md   what an agent reads            (scripts/gen-tools-md.py)
  skills/scio/server/tools.json     what the bridge lists keyless  (scripts/gen-tools-list.py)
  tests/wiki/tools.json             what the local stand-in serves (the source's bytes, verbatim)

Why one command: a release used to regenerate the first two only when a platform checkout sat beside this one — on
whatever branch it was on — and never the third, so the plugin could advertise inputs production refuses and its own
tests could pass against a contract nobody runs. Fails, and writes nothing, when the source cannot be read or is not a
contract: a release without the contract is not a release of the contract."""
import argparse, importlib.util, json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = "https://scio.md/v1/tools.json"
COPIES = ("skills/scio/references/tools.md", "skills/scio/server/tools.json", "tests/wiki/tools.json")


def generator(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(ROOT, "scripts", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_source(source):
    """The contract's bytes. A URL is fetched only from scio.md — the one host this repository talks to."""
    if "://" in source:
        if not source.startswith("https://scio.md/"):
            sys.exit(f"sync-contract.py: {source} is not on https://scio.md/ — the contract comes from the platform or from a file")
        request = urllib.request.Request(source, headers={"User-Agent": "ScioSkill/release (+https://scio.md)"})   # Cloudflare turns Python-urllib away
        try:
            with urllib.request.urlopen(request, timeout=30) as r:
                return r.read()
        except Exception as e:
            sys.exit(f"sync-contract.py: could not fetch {source} ({e}); nothing written")
    try:
        with open(source, "rb") as f:
            return f.read()
    except OSError as e:
        sys.exit(f"sync-contract.py: could not read {source} ({e}); nothing written")


def generate(raw, source):
    """{copy: bytes} for the three copies, or exit when `raw` is not a tool contract."""
    try:
        contract = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        sys.exit(f"sync-contract.py: {source} is not JSON ({e}); nothing written")
    tools = contract.get("tools") if isinstance(contract, dict) else None
    if (not isinstance(tools, list) or not tools or not isinstance(contract.get("errors"), dict)
            or not all(isinstance(t, dict) and {"name", "input", "output", "description", "rest", "auth"} <= set(t) for t in tools)):
        sys.exit(f"sync-contract.py: {source} is not a tool contract (tools with name, input, output…; errors); nothing written")
    return {COPIES[0]: generator("gen-tools-md").render(contract).encode("utf-8"),
            COPIES[1]: generator("gen-tools-list").render(contract).encode("utf-8"),
            COPIES[2]: raw}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", nargs="?", default=LIVE, help=f"a path, or a URL on https://scio.md/ (default {LIVE})")
    ap.add_argument("--check", action="store_true", help="compare, write nothing; exit 1 on a difference")
    a = ap.parse_args()
    wanted = generate(read_source(a.source), a.source)
    if a.check:
        differ = []
        for rel, data in wanted.items():
            try:
                with open(os.path.join(ROOT, rel), "rb") as f:
                    same = f.read().replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n")   # a CRLF checkout is the same file
            except OSError:
                same = False
            if not same:
                differ.append(rel)
        if differ:
            print(f"the contract at {a.source} differs from what this checkout carries: {', '.join(differ)}.\n"
                  f"Regenerate with `python3 scripts/sync-contract.py {a.source}` and cut a release (a regenerated contract is one).")
            sys.exit(1)
        print(f"all three copies match {a.source}")
        return
    for rel, data in wanted.items():
        path = os.path.join(ROOT, rel)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
    print(f"wrote {', '.join(COPIES)} from {a.source}")


if __name__ == "__main__":
    main()
