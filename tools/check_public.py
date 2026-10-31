#!/usr/bin/env python3
"""check_public.py: keep private things out of this public repo.

  python tools/check_public.py --staged      what `git commit` is about to record (the pre-commit hook runs this)
  python tools/check_public.py --all         every tracked file (CI runs this)
  python tools/check_public.py FILE...       just these files, read from disk
  python tools/check_public.py --selftest    prove every rule fires on a bad example and stays quiet on a good one

Exit 0 = clean. Exit 1 = something to fix: each finding is printed with file:line and the matched
text marked >>like this<< (keys and tokens are shortened so the hook output does not repeat them).
Exit 2 = the check itself could not run. The hook blocks on anything but 0.

What it blocks:
  - secret files: .env (but not .env.example), private keys, keystores, credentials json
  - private keys and API tokens inside text (Anthropic, OpenAI-style, GitHub, Slack, AWS, Google,
    Hugging Face, Stripe, Discord bot tokens and webhooks, Twilio, bearer tokens, key = "..." lines)
  - private-network and VPN-range IP addresses (10.x, 172.16-31.x, 192.168.x, 100.64-127.x)
  - URLs with a password in them, personal home-folder paths, email addresses
  - files over 10 MB
  - any audio file outside sounds/, or without a filled-in row in sounds/SOURCES.md

Your own private words (your machines' names, your clients' names) go in a file OUTSIDE the repo, so
the list itself stays private: one regex per line (case-insensitive, # starts a comment) in
~/.builder-office-share/extra-patterns.txt, or the file named by $BOS_EXTRA_PATTERNS.

Python 3.8+, standard library only. Works the same on Windows, macOS and Linux.
"""
import os
import re
import subprocess
import sys

MAX_BYTES = 10 * 1024 * 1024
AUDIO_EXT = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus", ".aac")
SOURCES = "sounds/SOURCES.md"
EMPTY_CELL = {"", "unknown", "?", "todo", "tbd", "n/a", "na", "none", "-", "--", "\u2014"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BAD_NAMES = [
    (re.compile(r"(^|/)\.env(\.(?!example$)[^/]+)?$"), "a .env file (commit a .env.example with placeholders instead)"),
    (re.compile(r"\.(pem|key|p12|pfx|ppk|kdbx|keystore|jks)$", re.I), "a key or keystore file"),
    (re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$"), "an ssh private key"),
    (re.compile(r"(^|/)(credentials|service[-_]account[^/]*)\.json$", re.I), "a credentials file"),
]

_OCT = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_PRIVATE_IP = (r"(?<![\d.])(?:10\.{o}|192\.168|172\.(?:1[6-9]|2\d|3[01])|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))"
               r"\.{o}\.{o}(?!\.?\d)").format(o=_OCT)
_HOME_PLACEHOLDER = r"(?i:<[^>]*>|you|your[\w-]*|user|username|name|me|public|runner|shared|default|ubuntu)(?:[\\/\s`'\"]|$)"

# (name, regex, shorten the match when printing it)
TEXT_RULES = [
    ("private key block", r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", False),
    ("Anthropic key", r"\bsk-ant-[A-Za-z0-9_\-]{20,}", True),
    ("OpenAI-style key", r"\bsk-(?:proj-|live-)?[A-Za-z0-9_\-]{32,}", True),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})", True),
    ("Slack token", r"\bxox[abposr]-[A-Za-z0-9\-]{10,}", True),
    ("AWS key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", True),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{35}", True),
    ("Hugging Face token", r"\bhf_[A-Za-z0-9]{30,}", True),
    ("Stripe key", r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}", True),
    ("Discord bot token", r"\b[MNO][A-Za-z\d_\-]{23,27}\.[A-Za-z\d_\-]{6}\.[A-Za-z\d_\-]{27,40}\b", True),
    ("Discord webhook", r"discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+", True),
    ("Twilio key", r"\bSK[0-9a-fA-F]{32}\b", True),
    ("bearer token", r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{20,}=*", True),
    ("password in a URL", r"\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]{3,}@", True),
    ("secret in an assignment", r"(?i)\b(?:api[_\-]?key|secret|token|passw(?:or)?d|auth[_\-]?key)\b[\"']?\s*[:=]\s*[\"']?"
                                r"(?P<v>[A-Za-z0-9_\-/+=.]{16,})", True),
    ("private or VPN IP address", _PRIVATE_IP, False),
    ("personal home-folder path", r"(?:\b[A-Za-z]:\\[Uu]sers\\|/Users/|/home/)(?!" + _HOME_PLACEHOLDER + r")[A-Za-z0-9._\-]+", False),
    ("email address", r"\b(?P<local>[A-Za-z0-9._%+\-]+)@(?P<domain>[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b", False),
]
TEXT_RULES = [(n, re.compile(p), s) for n, p, s in TEXT_RULES]

EMAIL_OK_LOCAL = {"git"}
EMAIL_OK_DOMAIN = re.compile(r"(?i)(^|\.)(example\.(com|org|net)|invalid|example|test|localhost|users\.noreply\.github\.com|noreply\.github\.com)$")
PLACEHOLDER_VALUE = re.compile(r"(?i)your|example|placeholder|changeme|xxxx|here|dummy|redacted")


def _skip(name, m):
    """True when a match is a known-safe shape (a placeholder value, a git ssh remote, a reserved domain)."""
    if name == "secret in an assignment":
        v = m.group("v")
        if PLACEHOLDER_VALUE.search(v) or re.fullmatch(r"[A-Z0-9_]+", v):
            return True
        return not (re.search(r"\d", v) and re.search(r"[A-Za-z]", v))   # real keys mix letters and digits
    if name == "email address":
        return m.group("local") in EMAIL_OK_LOCAL or bool(EMAIL_OK_DOMAIN.search(m.group("domain")))
    return False


def _shown(text, s, e, shorten):
    hit = text[s:e]
    if shorten and len(hit) > 8:
        hit = hit[:4] + "..." + hit[-2:]
    pre = text[max(0, s - 30):s].replace("\n", " ")
    post = text[e:e + 30].replace("\n", " ")
    return pre + ">>" + hit + "<<" + post


def load_extra(path=None):
    """[(pattern text, compiled)] from the private extra-patterns file; [] if there is none. A bad regex is an error, never skipped."""
    path = path or os.environ.get("BOS_EXTRA_PATTERNS") or os.path.join(os.path.expanduser("~"), ".builder-office-share", "extra-patterns.txt")
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                out.append((line, re.compile(line, re.I)))
            except re.error as e:
                raise ValueError("%s line %d is not a valid regex (%s); fix it, the check will not run without it" % (path, n, e))
    return out


def check_name(path):
    return ["%s  %s" % (path, why) for rx, why in BAD_NAMES if rx.search(path)]


def check_size(path, size):
    return ["%s  is %.1f MB; the limit here is %d MB (link big files instead)" % (path, size / 1048576.0, MAX_BYTES // 1048576)] if size > MAX_BYTES else []


def check_text(path, text, extra=()):
    out = []
    lines = text.split("\n")
    for i, line in enumerate(lines, 1):
        for name, rx, shorten in TEXT_RULES:
            for m in rx.finditer(line):
                if not _skip(name, m):
                    out.append("%s:%d  %s  %s" % (path, i, name, _shown(line, m.start(), m.end(), shorten)))
        for pat, rx in extra:
            for m in rx.finditer(line):
                out.append("%s:%d  private word (your extra-patterns list: %s)  %s" % (path, i, pat, _shown(line, m.start(), m.end(), False)))
    return out


def parse_sources(text):
    """{name: (source, license)} from the table in sounds/SOURCES.md; keyed by the path under sounds/ AND the bare file name."""
    rows = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0].lower() == "file" or all(re.fullmatch(r":?-+:?", c or "-") for c in cells):
            continue
        key = cells[0].replace("\\", "/").lstrip("./")
        if key.startswith("sounds/"):
            key = key[len("sounds/"):]
        rows[key] = (cells[2], cells[3])
        rows.setdefault(key.rsplit("/", 1)[-1], (cells[2], cells[3]))
    return rows


def check_audio(path, sources_text):
    if not path.lower().endswith(AUDIO_EXT):
        return []
    if not path.startswith("sounds/"):
        return ["%s  audio belongs under sounds/ (with a row in %s)" % (path, SOURCES)]
    rel = path[len("sounds/"):]
    rows = parse_sources(sources_text)
    row = rows.get(rel) or rows.get(rel.rsplit("/", 1)[-1])
    if not row:
        return ["%s  has no row in %s; add:  | %s | what it is | where it came from (link) | license | who added it |" % (path, SOURCES, rel)]
    src, lic = (c.strip().lower() for c in row)
    missing = [w for w, c in (("source", src), ("license", lic)) if c in EMPTY_CELL]
    if missing:
        return ["%s  its row in %s has no real %s; a clip we can't trace doesn't go in a public repo" % (path, SOURCES, " or ".join(missing))]
    return []


def _git(*args, binary=False):
    r = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()[:200]))
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def _is_binary(data):
    return b"\x00" in data[:8000]


def run(mode, files=()):
    extra = load_extra()
    if mode in ("staged", "all"):
        listing = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z") if mode == "staged" else _git("ls-files", "-z")
        paths = [p for p in listing.split("\0") if p]
        read = lambda p: _git("cat-file", "blob", ":" + p, binary=True)
        try:
            sources = _git("cat-file", "blob", ":" + SOURCES)
        except RuntimeError:
            sources = ""
    else:
        paths = [os.path.relpath(os.path.abspath(f), ROOT).replace("\\", "/") for f in files]
        read = lambda p: open(os.path.join(ROOT, p), "rb").read()
        sp = os.path.join(ROOT, SOURCES)
        sources = open(sp, encoding="utf-8").read() if os.path.isfile(sp) else ""
    found = []
    for p in paths:
        data = read(p)
        found += check_name(p) + check_size(p, len(data)) + check_audio(p, sources)
        if not _is_binary(data):
            found += check_text(p, data.decode("utf-8", "replace"), extra)
    return paths, found


def selftest():
    """Every rule must fire on a bad example and stay quiet on the good ones. Bad examples are assembled at run time so this
    file never contains a real-looking key itself."""
    bad = [
        ("private key block", "-----BEGIN " + "OPENSSH PRIVATE KEY-----"),
        ("Anthropic key", "key: sk-" + "ant-api03-" + "aB3dE5" * 5),
        ("OpenAI-style key", "OPENAI=sk-" + "proj-" + "Zq9" * 12),
        ("GitHub token", "gh" + "p_" + "A1b2" * 9),
        ("Slack token", "xox" + "b-1234567890-" + "abcdef"),
        ("AWS key id", "AK" + "IA" + "ABCDEFGHIJKLMNOP"),
        ("Google API key", "AI" + "za" + "Sy" + "A1b2C3d4E5" * 3 + "abcde"),
        ("Hugging Face token", "h" + "f_" + "aB3" * 11),
        ("Stripe key", "s" + "k_live_" + "a1B2c3D4e5F6g7H8"),
        ("Discord bot token", "M" + "T" * 23 + "." + "Gabcde" + "." + "x1" * 15),
        ("Discord webhook", "https://discord.com/api/" + "webhooks/123456/abcDEF_ghi"),
        ("Twilio key", "S" + "K" + "0123456789abcdef" * 2),
        ("bearer token", "Authorization: Bearer " + "abc123DEF456ghi789JKL0"),
        ("password in a URL", "postgres://admin:" + "hunter22" + "@" + "db.local/x"),
        ("secret in an assignment", 'api_key = "' + "a1B2c3D4e5F6g7H8i9" + '"'),
        ("private or VPN IP address", "ssh in at 192." + "168.1.20 first"),
        ("private or VPN IP address", "tailnet 100." + "101.5.7"),
        ("private or VPN IP address", "box at 10." + "0.0.5."),
        ("private or VPN IP address", "docker 172." + "20.1.1"),
        ("personal home-folder path", "C:\\" + "Users\\brad\\bot\\sfx.py"),
        ("personal home-folder path", "/" + "Users/alice/code"),
        ("personal home-folder path", "/c/" + "Users/mikey/bin"),
        ("email address", "write to alice" + "@" + "gmail.com"),
    ]
    good = [
        "use 192.0.2.10 in examples", "the default is 127.0.0.1:11434", "build 10.0.19045.1234", "CUDA 12.4.1",
        "C:\\Users\\<you>\\bots\\sfx.py", "/home/runner/work", "%USERPROFILE%\\.ssh", "~/.cache/huggingface",
        "git clone git@github.com:Org/repo.git", "dev@example.com", "bot@builder-office.invalid",
        "token = YOUR_TOKEN_GOES_HERE", "secret = load_secret_from_disk()", "password: <your-password>",
        "Authorization: Bearer <your-token>", "the sk-learn library", "play air_horn after the punchline",
        "pip install faster-whisper==1.1.0", "npm i @anthropic-ai/claude-code",
    ]
    fails = []
    fired = set()
    for rule, text in bad:
        hits = [h for h in check_text("x.md", text) if "  %s  " % rule in h]
        if hits:
            fired.add(rule)
        else:
            fails.append("MISSED %-28s %r -> %s" % (rule, text, check_text("x.md", text)))
    for text in good:
        hits = check_text("x.md", text)
        if hits:
            fails.append("FALSE ALARM %r -> %s" % (text, hits))
    untested = [n for n, _, _ in TEXT_RULES if n not in fired]
    if untested:
        fails.append("no bad example fires these rules (an untested rule is not a rule): %s" % untested)
    for p, want in ((".env", 1), ("bot/.env.local", 1), (".env.example", 0), ("keys/server.pem", 1), ("id_ed25519", 1),
                    ("id_ed25519.pub", 0), ("credentials.json", 1), ("notes/env-setup.md", 0)):
        if len(check_name(p)) != want:
            fails.append("NAME %r expected %d finding(s), got %s" % (p, want, check_name(p)))
    src = ("| file | what | source | license | added by |\n|---|---|---|---|---|\n"
           "| clips/air_horn.mp3 | horn | https://freesound.org/s/1/ | CC0 | jambot |\n"
           "| `clips/rimshot.wav` | drum | made by jambot | CC0 | jambot |\n"
           "| clips/mystery.mp3 | ? | unknown | unknown | jambot |\n"
           "| clips/half.mp3 | x | https://example.com/a | | jambot |\n")
    for p, want in (("sounds/clips/air_horn.mp3", 0), ("sounds/clips/rimshot.wav", 0), ("sounds/clips/mystery.mp3", 1),
                    ("sounds/clips/half.mp3", 1), ("sounds/clips/none.mp3", 1), ("music/song.mp3", 1), ("sounds/README.md", 0)):
        if len(check_audio(p, src)) != want:
            fails.append("AUDIO %r expected %d finding(s), got %s" % (p, want, check_audio(p, src)))
    if check_size("a.wav", MAX_BYTES + 1) == [] or check_size("a.wav", MAX_BYTES) != []:
        fails.append("SIZE limit not enforced at %d bytes" % MAX_BYTES)
    shown = check_text("x.md", "gh" + "p_" + "A1b2" * 9)[0]
    if "A1b2A1b2" in shown:
        fails.append("a token is printed in full: %s" % shown)
    for f in fails:
        print(f)
    print("selftest: %d bad examples, %d good examples, %d rules: %s" % (len(bad), len(good), len(TEXT_RULES), "FAIL" if fails else "ok"))
    return 1 if fails else 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    if argv[0] == "--selftest":
        return selftest()
    mode = {"--staged": "staged", "--all": "all"}.get(argv[0], "files")
    try:
        paths, found = run(mode, argv if mode == "files" else ())
    except Exception as e:  # noqa: BLE001 - any failure to look is a refusal, never a pass
        print("check_public: could not run (%s: %s); nothing was checked, so this blocks" % (type(e).__name__, e), file=sys.stderr)
        return 2
    for f in found:
        print("BLOCKED  " + f)
    if found:
        print("\n%d problem(s) in %d file(s) checked. Fix them and commit again (rules: README.md, 'Nothing private')." % (len(found), len(paths)))
        return 1
    print("check_public: %d file(s) clean" % len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
