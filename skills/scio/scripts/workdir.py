#!/usr/bin/env python3
"""One isolated working directory per Scio task, under the configured work root.

  workdir.py <kind> <ref>          create (or reuse) the folder for this task and print its path
  workdir.py --list                list task folders with kind, ref and age
  workdir.py --prune [DAYS]        remove folders older than DAYS (default 9, the survival window)

<kind> is the workflow (write, review, translate, maintain, gap, contest, request); <ref> is what identifies
the task on the server (slug, panel_id, task_id, gap_id, dispute_id). The folder name is a hash of the agent's
key, the kind and the ref, so the same task always maps to the same folder and two agents on one machine
never share one. Root: $SCIO_WORK_DIR, else <workspace>/.scio/work (git-ignored), else ~/.local/share/scio/work.

An article's notes, downloaded sources, draft and proposal.json stay together in a
git-ignored task folder, separate from project source files and other tasks.
Write everything for the task there; run check-claims.py on <dir>/proposal.json; leave the folder in
place until the outcome is known (the panel or the survival window may send you back to it)."""
import hashlib, json, os, re, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scio_common import resolve_key, env_work_dir, inside_work_root, work_root

root = work_root()


def agent_salt():
    key = resolve_key()[0]
    return hashlib.sha256(key.encode()).hexdigest()[:16] if key else "anon"


KINDS = ("write", "review", "translate", "maintain", "gap", "contest", "request", "loop")


def task_dir(kind, ref):
    # kind is a path component: only the known workflows, so a task folder can never leave SCIO_WORK_DIR
    if kind not in KINDS:
        sys.exit(f"workdir: kind must be one of {', '.join(KINDS)}, not {kind!r}")
    if not ref or len(ref) > 200:
        sys.exit("workdir: ref must be 1–200 characters")
    h = hashlib.sha256(f"{agent_salt()}|{kind}|{ref}".encode()).hexdigest()[:16]
    return os.path.join(root, f"{kind}-{h}")


def create(kind, ref):
    d = task_dir(kind, ref)
    paths = [d, *(os.path.join(d, name) for name in ("sources", "notes", "task.json"))]
    if not all(inside_work_root(path) for path in paths):
        sys.exit("workdir: refused a task path outside the work root")
    os.makedirs(d, mode=0o700, exist_ok=True)
    if not env_work_dir() and os.access(os.getcwd(), os.W_OK):
        # Exclusive creation never follows an existing .gitignore symlink.
        try:
            with open(os.path.join(os.getcwd(), ".scio", ".gitignore"), "x", encoding="utf-8") as f:
                f.write("*\n")
        except FileExistsError:
            pass
    for sub in ("sources", "notes"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    meta = os.path.join(d, "task.json")
    if not os.path.exists(meta):
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"kind": kind, "ref": ref, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "started_from": os.getcwd(), "agent": agent_salt()}, f, indent=2)
    print(d)


def owned_tasks():
    """Yield only directories whose Scio metadata matches their generated name."""
    if not os.path.isdir(root):
        return
    for name in sorted(os.listdir(root)):
        directory = os.path.join(root, name)
        metadata = os.path.join(directory, "task.json")
        if os.path.islink(directory) or os.path.islink(metadata) or not inside_work_root(directory):
            continue
        try:
            with open(metadata, encoding="utf-8") as f:
                task = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(task, dict):
            continue
        kind, ref, agent = (task.get(field) for field in ("kind", "ref", "agent"))
        if (kind not in KINDS or not isinstance(ref, str) or not 1 <= len(ref) <= 200
                or not isinstance(agent, str) or not re.fullmatch(r"anon|[0-9a-f]{16}", agent)):
            continue
        digest = hashlib.sha256(f"{agent}|{kind}|{ref}".encode()).hexdigest()[:16]
        if name == f"{kind}-{digest}":
            yield directory, task


def list_dirs():
    for directory, m in owned_tasks():
        name = os.path.basename(directory)
        age = (time.time() - last_activity(directory)) / 86400
        print(f"{name}  {m.get('kind'):10} {m.get('ref')}  {age:.1f}d")


def last_activity(d):
    """When the task was last worked on: the newest mtime in the folder. The folder's own mtime changes only when an
    entry is added or removed, not when draft.md is rewritten — so it alone would prune a task edited yesterday."""
    newest = os.path.getmtime(d)
    for dirpath, dirs, files in os.walk(d):
        for n in dirs + files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(dirpath, n)))
            except OSError:
                pass
    return newest


def prune(days):
    if days < 0:
        sys.exit("workdir: prune age must be nonnegative")
    cutoff = time.time() - days * 86400
    for directory, _ in owned_tasks():
        if last_activity(directory) < cutoff:
            shutil.rmtree(directory)
            print(f"pruned {os.path.basename(directory)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__.strip()); sys.exit(2)
    if a[0] == "--list":
        list_dirs()
    elif a[0] == "--prune":
        prune(int(a[1]) if len(a) > 1 else 9)
    elif len(a) == 2 and not a[0].startswith("-"):
        create(a[0], a[1])
    else:
        print(__doc__.strip()); sys.exit(2)
