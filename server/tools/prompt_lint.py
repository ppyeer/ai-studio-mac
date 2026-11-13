#!/usr/bin/env python3
"""Check a FastH3 prompt before it is rendered.

  prompt_lint.py prompt.txt [more.txt ...] [--secs 10]      exit 1 when any file has an ERROR

ERROR  a section of the structured form is missing; Chinese outside a spoken line (“…”, 「…」 or <d>…</d>),
       which FastH3 burns into the picture as subtitles; a clip shorter than 4.5 s.
WARN   no per-second beats in detailed_description; longer than 12 s; more than ~5 beats per 10 s;
       subject_definitions names someone who only enters later.

As a module: errors, warns = prompt_lint.lint(text, secs)
"""
import argparse
import re
import sys

SECTIONS = ("subject_definitions", "summary", "retention_analysis", "detailed_description",
            "overall_soundscape", "non_diegetic_music")
SPOKEN = re.compile(r"“[^”]*”|「[^」]*」|<d>.*?</d>", re.S)
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]+")
SHOT_RANGE = re.compile(r"\[Shot\s*\d+\]\s*\(?\s*\d+(?:\.\d+)?\s*[-–—~]\s*\d+(?:\.\d+)?\s*s\b\)?", re.I)
SHOT_AT = re.compile(r"\[Shot\s*\d+\]\s*At\s+\d{1,2}:\d{2}", re.I)
BEAT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-–—~]\s*(\d+(?:\.\d+)?)\s*s\b")
LATE = re.compile(r"\b(later|enters?|entering|arrives?|arriving|walks in|comes in|joins)\b", re.I)
MIN_SECS = 4.5
BEST_MAX_SECS = 12
BEATS_PER_10S = 5


def sections(text):
    """{section: body} of the structured form; a section starts a line as `name: ...`."""
    parts = re.split(rf"(?mi)^\s*({'|'.join(SECTIONS)})\s*:", text)
    return {parts[i].lower(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def lint(text, secs=None):
    """Return (errors, warns), two lists of messages."""
    errors, warns = [], []
    sec = sections(text)
    missing = [k for k in SECTIONS if k not in sec]
    if missing:
        errors.append("missing section(s): " + ", ".join(missing) + " (write all six: " + " / ".join(SECTIONS) + ")")

    blanked = SPOKEN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    seen = set()
    for m in CJK.finditer(blanked):
        if m.group(0) in seen:
            continue
        seen.add(m.group(0))
        line = text.count("\n", 0, m.start()) + 1
        errors.append(f"line {line}: Chinese outside a spoken line: {m.group(0)!r}. FastH3 burns description "
                      "Chinese into the picture as subtitles; write it in English and keep Chinese only inside “…”")

    if secs is not None and secs < MIN_SECS:
        errors.append(f"{secs} s is shorter than {MIN_SECS} s: FastH3 pads it and improvises filler speech; "
                      "render at least 4.5 s and cut it shorter in the edit")
    if secs is not None and secs > BEST_MAX_SECS:
        warns.append(f"{secs} s: takes are best up to {BEST_MAX_SECS} s; at 15 s costumes drift from about 8 s "
                     "and 20 s loops the action. Split it into shots")

    desc = sec.get("detailed_description", "")
    shots = len(SHOT_RANGE.findall(desc)) + len(SHOT_AT.findall(desc))
    beats = BEAT.findall(SHOT_RANGE.sub(" ", desc))
    if desc and not beats and not shots:
        warns.append("detailed_description has no per-second beats (\"0-2 s: ...\"); without them the body barely "
                     "moves and the take looks like a moving photo")
    dur = secs or max((float(b) for _, b in beats), default=0)
    if dur and len(beats) > BEATS_PER_10S * dur / 10:
        warns.append(f"{len(beats)} beats in {dur:g} s: more than ~{BEATS_PER_10S} per 10 s gets merged or skipped; "
                     "split the action chain into 2-3 shots on the same camera")

    late = LATE.search(sec.get("subject_definitions", ""))
    if late:
        warns.append(f"subject_definitions says {late.group(0)!r}: every defined subject shows up in the first frames. "
                     "Define only who is on screen at t=0 and bring late entrants in through their beat")
    return errors, warns


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check FastH3 prompts (structured English form).")
    ap.add_argument("files", nargs="+", help="prompt text files")
    ap.add_argument("--secs", type=float, help="clip length the prompt will be rendered at")
    a = ap.parse_args(argv)
    failed = False
    for f in a.files:
        with open(f, encoding="utf-8") as fh:
            errors, warns = lint(fh.read(), a.secs)
        for m in errors:
            print(f"{f}: ERROR {m}")
        for m in warns:
            print(f"{f}: WARN  {m}")
        if not errors and not warns:
            print(f"{f}: OK")
        failed |= bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
