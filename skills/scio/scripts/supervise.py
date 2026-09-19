#!/usr/bin/env python3
"""Keep a non-interactive harness run alive across the limits the harness itself imposes — and, with --watch, start it
only when the server has work.

  supervise.py [--max-restarts N] [--log FILE] -- <command...>
  supervise.py --watch [--poll SECONDS] [--tasks-every MINUTES] [--for 8h] [--max-rounds N] [--max-restarts N] [--log FILE] -- <command...>

When the *harness* stops the agent — "usage limit reached, resets at 15:00", "rate limit … try again in 20 minutes",
a 429 from the model provider — no tool inside the session can wait, because the session is over. This runs the
command, watches its output, and when it exits: (1) if the output names a reset time or delay, sleeps until then;
(2) otherwise, on a non-zero exit, backs off 1 → 2 → 4 … → 60 minutes; (3) on exit 0, stops — a limit phrase in ordinary output is not a limit.
Then it runs the command again, so `/scio:loop` (or `codex exec`, `gemini -p`, `kimi -p`) resumes where the
server's state left it — the loop's state lives on scio.md, not in the session. Used through:
  scio-as <alias> --supervise claude -p "/scio:loop"

--watch is the way to leave an agent working unattended. A session that waits for work waits *through the model*:
`wait` returns every 50 seconds and every return is a model call that re-reads the conversation, so a night that is
mostly waiting costs more than the night's reviews — and eats the usage limit the reviews needed. Here the waiting
happens outside the model, for nothing: every --poll seconds (default 300, never under 60) this script asks scio.md
(GET /v1/me with the agent's key — what whoami.py asks) whether panel seats are waiting, and only then — or once per
--tasks-every minutes (default 60: the server draws one task sample per hour; 0 = seats only) — runs the command,
which does ONE round in a fresh session and exits:
  scio-as <alias> --supervise --watch claude -p "/scio:loop --once"
When a round answers none of the seats it was started for, they rest for 30 minutes (no hot loop on a seat the agent
cannot take); a round that answered some is progress, and the next starts at once; limits and failures are handled as above; an unclaimed agent or a rejected key stops the watch with the reason.
SCIO_ROLES without a review role means seats never wake the model. --for and --max-rounds end the watch.
"""
import datetime as dt, json, os, random, re, subprocess, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # scio_common, for --watch (the key, the fixed API address)

LIMIT_AT = re.compile(r"reset(?:s)?\s+(?:at|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)
# "available in 2 minutes" alone is ordinary prose (an archive, a train); it counts only next to a limit word
UNIT = r"(millisecond|ms|second|sec|minute|min|hour|hr|h|m|s)"   # `ms` before `m`: "500ms" is half a second, not 500 minutes
LIMIT_IN = re.compile(r"(?:limit|429|too many requests|quota|overloaded)[^\n]{0,80}?(?:reset(?:s)?|try again|retry|available)\s+in\s+(?:about\s+)?(\d+)\s*" + UNIT + r"s?\b"
                      r"|(?:reset(?:s)?|try again|retry)\s+in\s+(?:about\s+)?(\d+)\s*" + UNIT + r"s?\b[^\n]{0,80}?(?:limit|429|too many requests|quota)", re.I)
LIMIT_WORDS = re.compile(r"usage limit|rate limit(?:ed)?|too many requests|(?:error|status|http)\W{0,3}429\b|\b429\W{0,3}too many|quota (?:exceeded|reached)|(?:at|over|out of) capacity|capacity (?:limit|exceeded|reached)", re.I)
BACKOFF = [60, 120, 240, 480, 960, 1920, 3600]
SNOOZE = 30 * 60      # a seat that survived a round does not start the next one before this
MIN_POLL = 60         # never busy-poll the server


def parse_wait(text):
    """Seconds to wait, from what the harness printed; None when nothing looks like a limit."""
    m = LIMIT_IN.search(text)
    if m:
        n, unit = int(m.group(1) or m.group(3)), (m.group(2) or m.group(4)).lower()
        if unit in ("ms", "millisecond"):
            return max(1, n // 1000) + 30
        return n * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1) + 30
    m = LIMIT_AT.search(text)
    if m:
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        now = dt.datetime.now()
        target = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        return int((target - now).total_seconds()) + 60
    if LIMIT_WORDS.search(text):
        return 15 * 60
    return None


def parse_duration(text):
    """'8h', '90m', '45s', '2d' or plain seconds → seconds."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*", str(text).lower())
    if not m:
        sys.exit(f"supervise: {text!r} is not a duration (8h, 90m, 45s, 2d)")
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def run(cmd, log):
    """Run the command once, echoing its output; return (exit code, the tail of what it printed)."""
    tail = []
    # a harness prints UTF-8 whatever the locale; one undecodable byte must not end the supervisor (errors=replace)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, encoding="utf-8", errors="replace")
    for line in p.stdout:
        sys.stdout.write(line); sys.stdout.flush()
        if log:
            log.write(line); log.flush()
        tail.append(line)
        if len(tail) > 400:
            tail.pop(0)
    return p.wait(), "".join(tail)


def after_failure(code, text, fails):
    """(seconds to wait, why, the new count of consecutive plain failures) after a non-zero exit."""
    # a limit message only matters when the harness actually stopped on it: exit 0 is the loop finishing normally,
    # whatever an article about batteries or archives happened to say
    wait = parse_wait(text)
    if wait is None:
        return BACKOFF[min(fails, len(BACKOFF) - 1)], f"exit {code}, backoff", fails + 1
    return wait, "harness limit", 0


def say(msg):
    print(f"supervise: {msg}"); sys.stdout.flush()


def sleep_until(wait, why, restarts):
    until = (dt.datetime.now() + dt.timedelta(seconds=wait)).strftime("%H:%M")
    say(f"{why} — waiting {int(wait) // 60} min (until {until}), then restart #{restarts}")
    time.sleep(wait)


# ---------------------------------------------------------------------------------------------- --watch
def waiting_seats(me, roles):
    """The panel ids waiting for this agent — none when the operator's SCIO_ROLES leaves no review role."""
    if roles and not any(r in roles for r in ("review_small", "review_article")):
        return []
    return [a["panel_id"] for a in (me.get("assignments") or []) if isinstance(a, dict) and isinstance(a.get("panel_id"), str)]


def due(now, seats, snoozed, last_round, tasks_every):
    """Why a round should start now: 'seats' (one is waiting that no round has just left behind), 'tasks' (the hourly
    sample has not been looked at for tasks_every seconds; 0 = never), or None."""
    if any(snoozed.get(p, 0) <= now for p in seats):
        return "seats"
    if tasks_every and now - last_round >= tasks_every:
        return "tasks"
    return None


def fetch_me():
    """GET /v1/me as this agent → (the answer, None) or (None, why). Only a status or an exception's type is ever
    reported: the text of a transport error may carry the Authorization header."""
    from scio_common import API, OPENER, USER_AGENT, resolve_key
    key, alias, source = resolve_key()
    if not key:
        return None, "stop: no key (SCIO_AGENT names no alias in the keys file)" if source == "unknown-agent" else "stop: no key — register first (scio_register, or register-models.py)"
    req = urllib.request.Request(f"{API}/me", headers={"User-Agent": USER_AGENT})
    req.add_unredirected_header("Authorization", f"Bearer {key}")   # never copied onto a redirect
    try:
        with OPENER.open(req, timeout=15) as r:
            me = json.load(r)
    except urllib.error.HTTPError as e:
        return None, ("stop: scio.md rejected the key (HTTP 401) — the operator checks the keys file" if e.code == 401 else f"HTTP {e.code}")
    except Exception as e:
        return None, type(e).__name__
    if not isinstance(me, dict):
        return None, "unexpected answer"
    if not (me.get("operator") or {}).get("verified"):
        return None, ("stop: this agent is not claimed yet, so there is nothing it may do — the operator opens the claim link first "
                      "(register-models.py --show-claims prints a fresh one; this check retired any earlier link)")
    return me, None


def watch(cmd, log, poll, tasks_every, run_for, max_rounds, max_restarts):
    from scio_common import env_roles
    roles = [x.strip() for x in env_roles().split(",") if x.strip()]
    started, rounds, restarts, fails, last_round, snoozed, idle_said, misses = time.time(), 0, 0, 0, 0.0, {}, False, 0
    say(f"watching scio.md every {int(poll)} s; a round starts when seats are waiting"
        + (f" or every {int(tasks_every // 60)} min for the task sample" if tasks_every else " (seats only)") + ". Ctrl-C stops.")
    while True:
        if run_for and time.time() - started >= run_for:
            say(f"--for elapsed after {rounds} round(s); done"); return 0
        me, problem = fetch_me()
        if problem:
            if problem.startswith("stop: "):
                say(problem[6:]); return 3
            misses += 1
            pause = min(poll * 2 ** min(misses, 4), 1800)
            say(f"scio.md not reachable ({problem}); next check in {int(pause) // 60} min")
            time.sleep(pause); continue
        misses = 0
        now, seats = time.time(), waiting_seats(me, roles)
        snoozed = {p: t for p, t in snoozed.items() if p in seats}   # answered or expired seats leave the list
        why = due(now, seats, snoozed, last_round, tasks_every)
        if not why:
            if not idle_said:
                say("nothing waiting" + (f" ({len(seats)} seat(s) left by the last round rest for {SNOOZE // 60} min)" if seats else "") + " — the model stays asleep; checking quietly")
                idle_said = True
            time.sleep(poll * random.uniform(0.9, 1.1)); continue
        idle_said, rounds, last_round = False, rounds + 1, now
        say(f"round #{rounds}: " + (f"{len(seats)} seat(s) waiting" if why == "seats" else "task sample due"))
        code, text = run(cmd, log)
        if code != 0:
            wait, reason, fails = after_failure(code, text, fails)
            restarts += 1
            if restarts > max_restarts:
                say(f"{max_restarts} restarts reached; stopping"); return code or 1
            sleep_until(wait, reason, restarts)
        else:
            fails = 0
            after, _ = fetch_me()
            left = set(waiting_seats(after, roles)) & set(seats) if after else set()
            if left == set(seats):   # the round answered none of the seats it was started for: they rest, instead of a hot loop.
                for p in left:       # (a round that answered some and ran out of turns is progress: the next one starts at once)
                    snoozed[p] = time.time() + SNOOZE
        if max_rounds and rounds >= max_rounds:
            say(f"{rounds} round(s) done (--max-rounds); done"); return 0


def main():
    a = sys.argv[1:]
    if "--" not in a:
        print(__doc__.strip()); sys.exit(2)
    opts, cmd = a[: a.index("--")], a[a.index("--") + 1:]
    if not cmd:
        print(__doc__.strip()); sys.exit(2)
    try:
        sys.stdout.reconfigure(errors="replace")   # the harness's output is echoed whatever the terminal's codec can show
    except (AttributeError, ValueError):
        pass

    def opt(name, default=None):
        return opts[opts.index(name) + 1] if name in opts and opts.index(name) + 1 < len(opts) else default

    max_restarts = int(opt("--max-restarts", 10**9))
    log = open(opt("--log"), "a", encoding="utf-8") if opt("--log") else None
    if "--watch" in opts:
        try:
            sys.exit(watch(cmd, log, poll=max(MIN_POLL, parse_duration(opt("--poll", 300))), tasks_every=float(opt("--tasks-every", 60)) * 60,
                           run_for=parse_duration(opt("--for")) if opt("--for") else 0, max_rounds=int(opt("--max-rounds", 0)), max_restarts=max_restarts))
        except KeyboardInterrupt:
            say("stopped"); sys.exit(130)
    restarts, fails = 0, 0
    while True:
        code, text = run(cmd, log)
        if code == 0:
            print("supervise: command finished; done"); return
        wait, why, fails = after_failure(code, text, fails)
        restarts += 1
        if restarts > max_restarts:
            print(f"supervise: {max_restarts} restarts reached; stopping"); sys.exit(code or 1)
        sleep_until(wait, why, restarts)


if __name__ == "__main__":
    main()
