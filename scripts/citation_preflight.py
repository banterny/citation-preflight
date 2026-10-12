#!/usr/bin/env python3
"""citation_preflight: check neutral citations against Find Case Law.

Two commands:

  scan FILE     list every citation found in a text file (no network)
  check FILE    check a JSON list of citations and print a Markdown report

FILE may be "-" for standard input. `check` takes a JSON list of objects:

  [{"citation": "[2015] UKSC 11",
    "name": "Montgomery v Lanarkshire Health Board",   (optional)
    "paras": [87, "108-109"],                          (optional)
    "court": "Supreme Court",                          (optional)
    "date": "2015-03-11"}]                             (optional)

Python 3.9 or later, standard library only. The only host contacted is
caselaw.nationalarchives.gov.uk, at most one request a second, and only for
the judgments the listed citations point to. It never searches or crawls.
"""

import argparse
import datetime
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

VERSION = "2026.10.12"
FCL = "https://caselaw.nationalarchives.gov.uk"
USER_AGENT = (
    "citation-preflight/" + VERSION
    + " (checks the citations in one document, one judgment at a time)"
)
AKN = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0}"
UKNS = "{https://caselaw.nationalarchives.gov.uk/akn}"
SNIPPET_LIMIT = 12
ATTRIBUTION = "Contains information licensed under the Open Justice - Licence v2.0."

# ---------------------------------------------------------------------------
# Courts that Find Case Law addresses by neutral citation.
#
# The court codes, divisions and address shapes below restate the patterns in
# data/neutral_citation_regex.yaml of ds-caselaw-utils v5.1.0:
#   Copyright (C) 2022 Crown Copyright (The National Archives), MIT licence.
#   https://github.com/nationalarchives/ds-caselaw-utils
# UKFTT (IAC) is added from Find Case Law's own court list.
# ---------------------------------------------------------------------------
PLAIN_COURTS = ["UKSC", "UKPC", "UKIPTrib", "EWFC", "EWCOP", "EWCC", "EWCR", "EAT", "UKAIT"]
DIVISIONS = {
    "EWHC": ["KB", "QB", "Admin", "Ch", "Comm", "Fam", "TCC", "Pat", "IPEC",
             "Costs", "SCCO", "Admlty", "BP", "Mercantile"],
    "UKUT": ["AAC", "IAC", "LC", "TCC"],
    "UKFTT": ["TC", "GRC", "PC", "HESC", "IAC"],
    "EWCOP": ["T1", "T2", "T3"],
    "EWFC": ["B"],
}
DIVISION_REQUIRED = {"EWHC", "UKUT", "UKFTT"}
EWCA_DIVISIONS = ["Civ", "Crim"]

# A court code outside the table above has no Find Case Law address, so it is
# reported as outside coverage whatever it is. These three are named in the
# message. Each was confirmed in use in Montgomery [2015] UKSC 11, which cites
# [2004] UKHL 41, [2013] CSIH 3 and [2010] CSOH 104.
NOT_ON_FCL = {
    "UKHL": "the House of Lords",
    "CSIH": "the Court of Session, Inner House",
    "CSOH": "the Court of Session, Outer House",
}

# Year of the earliest judgment Find Case Law holds for each court, as shown at
# https://caselaw.nationalarchives.gov.uk/courts-and-tribunals on 12 October 2026.
COVERAGE_READ = "12 October 2026"
EARLIEST = {
    "uksc": 2009, "ukpc": 2009, "ewca/civ": 2001, "ewca/crim": 2003,
    "ewhc/admin": 2003, "ewhc/admlty": 2003, "ewhc/ch": 2003, "ewhc/bp": 2026,
    "ewhc/comm": 2003, "ewhc/fam": 2003, "ewhc/ipec": 2013, "ewhc/kb": 2003,
    "ewhc/qb": 2003, "ewhc/mercantile": 2008, "ewhc/pat": 2003,
    "ewhc/scco": 2003, "ewhc/costs": 2003, "ewhc/tcc": 2003,
    "ewcr": 2020, "ewcc": 2019, "ewfc": 2014, "ewcop": 2009, "ukiptrib": 2023,
    "eat": 2021, "ukut/aac": 2011, "ukut/iac": 2007, "ukut/lc": 2014,
    "ukut/tcc": 2016, "ukftt/hesc": 1985, "ukftt/grc": 2009, "ukftt/iac": 2026,
    "ukftt/tc": 2009,
}

COURT_WORDS = {
    "UKSC": ["supreme court", "uksc"],
    "UKPC": ["privy council", "ukpc"],
    "EWCA": ["court of appeal", "ewca"],
    "EWHC": ["high court", "divisional court", "administrative court", "king's bench",
             "queen's bench", "chancery", "commercial court", "family division",
             "technology and construction", "patents court", "ewhc"],
    "EWCOP": ["court of protection"],
    "EWFC": ["family court"],
    "EWCC": ["county court"],
    "EWCR": ["crown court"],
    "EAT": ["employment appeal tribunal"],
    "UKUT": ["upper tribunal"],
    "UKFTT": ["first-tier tribunal", "first tier tribunal"],
}

# ---------------------------------------------------------------------------
# Finding and parsing citations
# ---------------------------------------------------------------------------
NEUTRAL_RE = re.compile(
    r"\[(?P<year>\d{4})\]\s+"
    r"(?P<court>EAT|CSIH|CSOH|HCJAC|HCJ|(?:EW|UK|NI)[A-Za-z]{2,8})\s+"
    r"(?:(?P<pre>[A-Za-z]{2,10})\s+)?"
    r"(?P<num>\d+)\b"
    r"(?:\s*\((?P<div>[A-Za-z0-9]{1,10})\))?"
)
REPORT_RE = re.compile(
    r"(?:\[(?P<year>\d{4})\]\s+(?:\d{1,3}\s+)?|\((?P<ryear>\d{4})\)\s+\d{1,3}\s+)"
    r"(?P<series>[A-Z][A-Za-z'’.&]*(?:\s+[A-Z][A-Za-z'’.&]*){0,4})\s+"
    r"(?P<page>[A-Z]{0,2}\d+)\b"
)
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"}


def _near(a, b):
    """True if `a` is `b` with two letters swapped or one letter wrong."""
    if len(a) != len(b):
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    if len(diff) == 1:
        return True
    return len(diff) == 2 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]


def mistyped_court(text):
    """Spot a neutral citation whose court code is misspelt, e.g. [2024] EHWC 12 (KB).

    Without this it would pass as a law-report citation. Returns the reason, or None.
    """
    m = REPORT_RE.search(text)
    if not m or NEUTRAL_RE.search(text):
        return None
    words = m.group("series").split()
    code = words[0].upper()
    rest = text[m.end():]
    known = [c.upper() for c in PLAIN_COURTS + list(DIVISIONS) + ["EWCA", "UKHL"] if len(c) >= 4]
    all_divs = [d.lower() for ds in DIVISIONS.values() for d in ds]
    near = len(code) >= 4 and any(_near(code, k) for k in known)
    div = re.match(r"\s*\(([A-Za-z0-9]{1,10})\)", rest)
    has_div = bool(div and div.group(1).lower() in all_divs)
    has_civ = len(words) == 2 and words[1].lower() in ("civ", "crim")
    if near or ((has_div or has_civ) and len(words) <= 2 and code.isalpha() and len(code) >= 3
                and code not in ("WLR", "ALL")):
        return "'%s' is not a court code this check recognises; check for a typing error" % words[0]
    return None


def _canon(value, options):
    """Return the spelling in `options` matching `value` ignoring case, else None."""
    for option in options:
        if option.lower() == (value or "").lower():
            return option
    return None


def parse_neutral(text):
    """Parse the first neutral citation in `text`. Returns a dict or None."""
    m = NEUTRAL_RE.search(text)
    if not m:
        return None
    all_courts = PLAIN_COURTS + list(DIVISIONS) + ["EWCA"] + list(NOT_ON_FCL)
    court = _canon(m.group("court"), all_courts) or m.group("court")
    pre, div = m.group("pre"), m.group("div")
    if court not in DIVISIONS and court != "EWCA":
        div = None  # a bracketed word after e.g. a UKSC citation is not a division
    nonstandard = False
    if pre and court == "EWHC" and not div:
        div, pre = pre, None  # old order: [2001] EWHC Admin 123
    elif pre and court in ("UKUT", "UKFTT") and not div:
        div, pre, nonstandard = pre, None, True  # [2010] UKUT AAC 1
    elif court == "EWCA" and not pre and _canon(div, EWCA_DIVISIONS):
        pre, div, nonstandard = _canon(div, EWCA_DIVISIONS), None, True  # [2001] EWCA 123 (Civ)
    return {
        "year": int(m.group("year")), "court": court, "pre": pre,
        "num": int(m.group("num")), "div": div, "nonstandard": nonstandard,
        "text": re.sub(r"\s+", " ", m.group(0)).strip(), "span": m.span(),
    }


def render(c, div=None):
    """Write a parsed citation in standard form, optionally with another division."""
    if c["court"] == "EWCA":
        return "[%d] EWCA %s %d" % (c["year"], div or c["pre"] or "?", c["num"])
    d = div if div is not None else c["div"]
    out = "[%d] %s %d" % (c["year"], c["court"], c["num"])
    return out + (" (%s)" % d if d else "")


def slug_for(c):
    """Find Case Law address path for a parsed citation.

    Returns (slug, problem). `slug` is None when no address can be built;
    `problem` then says why. An unknown division still gets a slug, so that a
    division added to Find Case Law after this table was written still resolves.
    """
    court, year, num = c["court"], c["year"], c["num"]
    if court == "EWCA":
        division = _canon(c["pre"], EWCA_DIVISIONS)
        if not division:
            return None, "an EWCA citation needs Civ or Crim before the number"
        return "ewca/%s/%d/%d" % (division.lower(), year, num), None
    if c["pre"]:
        return None, "'%s' is not expected before the number in a %s citation" % (c["pre"], court)
    if court in DIVISIONS:
        if c["div"]:
            return "%s/%s/%d/%d" % (court.lower(), c["div"].lower(), year, num), None
        if court in DIVISION_REQUIRED:
            return None, "a %s citation needs a division or chamber in brackets" % court
    if court in PLAIN_COURTS or court in DIVISIONS:
        return "%s/%d/%d" % (court.lower(), year, num), None
    return None, "'%s' is not a court code this check recognises" % court


def sibling_slugs(c):
    """Other addresses the same year and number could sit at (wrong division)."""
    court, year, num = c["court"], c["year"], c["num"]
    out = []
    if court == "EWCA":
        for d in EWCA_DIVISIONS:
            if d.lower() != (c["pre"] or "").lower():
                out.append(("ewca/%s/%d/%d" % (d.lower(), year, num), d))
    elif court in DIVISIONS:
        if court not in DIVISION_REQUIRED and c["div"]:
            out.append(("%s/%d/%d" % (court.lower(), year, num), ""))
        for d in DIVISIONS[court]:
            if d.lower() != (c["div"] or "").lower():
                out.append(("%s/%s/%d/%d" % (court.lower(), d.lower(), year, num), d))
    return out


PARA_REF_RE = re.compile(
    r"\[\d{1,4}(?:\([a-z]+\))?\](?:\s*[-–—]\s*\[\d{1,4}(?:\([a-z]+\))?\])?"
    r"|\bpara(?:graph)?s?\.?\s+\d{1,4}(?:\s*(?:[-–—]|to|and)\s*\d{1,4})?", re.I)


def scan_paragraph_refs(text):
    """List the paragraph references on each line, so that none is overlooked."""
    out = []
    for number, line in enumerate(text.split("\n"), 1):
        spans = [m.span() for m in NEUTRAL_RE.finditer(line)]
        spans += [m.span() for m in REPORT_RE.finditer(line)]
        refs = [m.group(0) for m in PARA_REF_RE.finditer(line)
                if not any(a <= m.start() < b for a, b in spans)]
        if refs:
            text_line = line.strip()
            out.append({"line": number, "refs": refs,
                        "text": text_line if len(text_line) <= 240 else text_line[:240] + "…"})
    return out


def scan_text(text):
    """List every neutral and law-report citation in `text`, in order."""
    found, taken = [], []
    for m in NEUTRAL_RE.finditer(text):
        c = parse_neutral(m.group(0))
        if c is None:
            continue
        found.append((m.start(), render(c) if slug_for(c)[0] else c["text"], "neutral"))
        taken.append(m.span())
    for m in REPORT_RE.finditer(text):
        if any(a < m.end() and m.start() < b for a, b in taken):
            continue
        if m.group("series").split()[0].lower() in MONTHS:
            continue
        tail = re.match(r"\s*\([A-Za-z0-9]{1,10}\)", text[m.end():])
        whole = text[m.start():m.end() + (tail.end() if tail else 0)]
        if mistyped_court(whole):
            found.append((m.start(), re.sub(r"\s+", " ", whole), "neutral"))
            continue
        found.append((m.start(), re.sub(r"\s+", " ", m.group(0)), "law report"))
    found.sort()
    lines = text.split("\n")
    starts, pos = [], 0
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1
    results, index = [], {}
    for offset, citation, kind in found:
        line_no = max(i for i, s in enumerate(starts) if s <= offset)
        if citation in index:
            index[citation]["lines"].append(line_no + 1)
            continue
        col = offset - starts[line_no]
        context = lines[line_no][max(0, col - 90):col + len(citation) + 60].strip()
        entry = {"citation": citation, "kind": kind, "lines": [line_no + 1], "context": context}
        index[citation] = entry
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
class Fetcher:
    """One polite request a second; remembers answers; stops if rate-limited."""

    def __init__(self, offline=False):
        self.offline = offline
        self.last = 0.0
        self.cache = {}
        self.blocked = None

    def get(self, url, method="GET"):
        """Return (status, body). Status 0 means the request could not be made."""
        key = (method, url)
        if key in self.cache:
            return self.cache[key]
        if self.offline:
            return 0, b"offline"
        if self.blocked:
            return 0, self.blocked.encode()
        wait = 1.0 - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = (resp.status, resp.read())
        except urllib.error.HTTPError as err:
            if err.code == 429:
                self.blocked = "Find Case Law rate limit reached (HTTP 429)"
            result = (err.code, b"")
        except (urllib.error.URLError, OSError) as err:
            result = (0, str(getattr(err, "reason", err)).encode())
        self.cache[key] = result
        return result


# ---------------------------------------------------------------------------
# Reading a judgment
# ---------------------------------------------------------------------------
def _text(el):
    return re.sub(r"\s+", " ", html.unescape("".join(el.itertext()))).strip()


def _top_paragraphs(el, out):
    """Collect numbered paragraphs, skipping anything quoted from another document."""
    for child in el:
        if child.tag in (AKN + "embeddedStructure", AKN + "quotedStructure"):
            continue
        if child.tag == AKN + "paragraph":
            out.append(child)
            continue  # a paragraph inside a paragraph is quoted material
        _top_paragraphs(child, out)


NUMBERING_GAP = 5


def out_of_sequence(numbers):
    """Positions of paragraph numbers that are not part of the judgment's own run.

    A quoted paragraph that the XML does not mark as a quotation shows up as a
    jump in the numbering which then returns to where it left off. A jump that
    never returns is taken to be the judgment's own numbering and is kept.
    """
    strays, pending, last = [], [], None
    for i, n in enumerate(numbers):
        if last is None:
            if n <= NUMBERING_GAP:
                last = n
            else:
                pending.append(i)
        elif last < n <= last + NUMBERING_GAP or n == 1:
            strays += pending
            pending, last = [], n
        else:
            pending.append(i)
    floor = last or 0
    for i in pending:
        if numbers[i] > floor:
            floor = numbers[i]
        else:
            strays.append(i)
    return set(strays)


def read_judgment(xml_bytes):
    """Pull name, date, own citation and numbered paragraphs out of the XML."""
    info = {"name": None, "date": None, "cite": None, "paras": {}, "repeated": [],
            "strays": set()}
    # Find Case Law's XML declares no DTD or entities. Refuse any that does, so a
    # hostile response cannot use entity expansion against the standard parser.
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        return None
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    work = root.find(".//" + AKN + "FRBRWork")
    if work is not None:
        name = work.find(AKN + "FRBRname")
        date = work.find(AKN + "FRBRdate")
        info["name"] = html.unescape(name.get("value") or "") or None if name is not None else None
        info["date"] = date.get("date") if date is not None else None
    cite = root.find(".//" + UKNS + "cite")
    if cite is not None and cite.text:
        info["cite"] = cite.text.strip()
    bodies = list(root.iter(AKN + "judgmentBody")) or [root]
    paragraphs = []
    for body in bodies:
        _top_paragraphs(body, paragraphs)
    numbered = []
    for p in paragraphs:
        num = p.find(AKN + "num")
        if num is None:
            continue
        m = re.match(r"^\[?(\d+)\]?\.?$", _text(num))
        if m:
            numbered.append((int(m.group(1)), _text(p)[len(_text(num)):].strip()))
    strays = out_of_sequence([n for n, _ in numbered])
    for i, (n, body_text) in enumerate(numbered):
        if i in strays:
            continue
        if n in info["paras"]:
            info["repeated"].append(n)
        else:
            info["paras"][n] = body_text
    for i in strays:
        n = numbered[i][0]
        if n in info["paras"]:
            info["repeated"].append(n)
        else:
            info["strays"].add(n)
    return info


def snippet(text, limit=150):
    """Opening words of a paragraph, cut at a word boundary."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------
NAME_STOP = {"v", "vs", "r", "re", "the", "of", "and", "on", "in", "a", "an", "for",
             "others", "ors", "anor", "another", "application", "ex", "parte",
             "ltd", "limited", "plc"}


def _words(name):
    name = re.sub(r"[’']", "", name.lower())
    return re.findall(r"[a-z0-9]+", name)


def name_score(written, official):
    """Share of the distinctive words in the name as written that FCL's name has.

    A written word also counts if it is the initials of consecutive words in
    FCL's name, so "MoD" matches "Ministry of Defence". A name matched by
    initials alone never scores above a half, so it cannot verify by itself.
    """
    want = [w for w in _words(written) if w not in NAME_STOP]
    if not want:
        return None
    have_all = _words(official)
    have = set(have_all)
    initials = set()
    for words in (have_all, [w for w in have_all if w not in NAME_STOP]):
        for size in range(2, 7):
            for i in range(len(words) - size + 1):
                initials.add("".join(w[0] for w in words[i:i + size]))
    literal = sum(1 for w in want if w in have)
    by_initials = sum(1 for w in want if w not in have and len(w) > 1 and w in initials)
    score = (literal + by_initials) / float(len(want))
    return min(score, 0.5) if literal == 0 else score


def name_label(written):
    """How the name comparison is described in the report."""
    distinctive = [w for w in _words(written) if w not in NAME_STOP]
    return "name (short form)" if len(distinctive) == 1 else "name"


COURT_ABBREVIATIONS = {
    "UKSC": ["sc"], "UKPC": ["pc", "jcpc"], "EWCA": ["ca"],
    "EWHC": ["hc", "kbd", "qbd", "kb", "qb"], "EWCOP": ["cop"], "UKUT": ["ut"], "UKFTT": ["ftt"],
    "EAT": ["eat"],
}


def _names_court(written, code):
    if any(k in written for k in COURT_WORDS.get(code, [])):
        return True
    tokens = re.findall(r"[a-z]+", written)
    return any(a in tokens for a in COURT_ABBREVIATIONS.get(code, []))


def court_check(written_court, court_code):
    """Compare the court named in the draft with the citation's court.

    Returns "match", "conflict" (the draft clearly names a different court) or
    "unknown" (the words were not recognised, so nothing was compared).
    """
    w = (written_court or "").lower().replace("’", "'")
    if _names_court(w, court_code):
        return "match"
    if any(_names_court(w, code) for code in COURT_WORDS if code != court_code):
        return "conflict"
    return "unknown"


def parse_date(value):
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def has_subparagraphs(values):
    return any(re.search(r"\d\s*\([a-z]+\)", str(v)) for v in values or [])


MAX_RANGE = 200
_RANGE_RE = re.compile(r"(\d+)(?:\([a-z]+\))?\]?(?:\s*[-–—]\s*\[?(\d+))?")


def parse_paras(values):
    """Turn [87, "108-109", "[66]"] into a sorted list of paragraph numbers.

    A range that is reversed or wider than MAX_RANGE contributes only its two
    ends; `unchecked_ranges` reports it so that it is never passed silently.
    """
    out = set()
    for value in values or []:
        for a, b in _RANGE_RE.findall(str(value)):
            lo, hi = int(a), int(b or a)
            if hi < lo or hi - lo > MAX_RANGE:
                out.update((lo, hi))
            else:
                out.update(range(lo, hi + 1))
    return sorted(out)


def unchecked_ranges(values):
    """Ranges that parse_paras did not expand in full."""
    return ["%s-%s" % (a, b) for value in values or []
            for a, b in _RANGE_RE.findall(str(value))
            if b and (int(b) < int(a) or int(b) - int(a) > MAX_RANGE)]


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------
VERIFIED, MISMATCH, NOT_FOUND = "Verified", "Mismatch", "Not found on FCL"
MALFORMED, OUTSIDE = "Malformed", "Outside coverage"
LAW_REPORT, NOT_CHECKED = "Not checkable here", "Not checked"
ORDER = [MISMATCH, NOT_FOUND, MALFORMED, NOT_CHECKED, OUTSIDE, LAW_REPORT, VERIFIED]


def _compare(entry, c, info, result):
    """Compare what the draft says with what Find Case Law holds."""
    problems, notes, checked = [], [], []
    if info["name"]:
        result["fcl_name"] = info["name"]
    if entry.get("name") and info["name"]:
        score = name_score(entry["name"], info["name"])
        checked.append(name_label(entry["name"]))
        if score is not None and score < 0.5:
            problems.append("different case: FCL holds *%s* at this citation, so either the "
                            "name or the citation is wrong" % info["name"])
        elif score is not None and score < 1:
            problems.append("name partly differs: FCL has *%s*" % info["name"])
    elif info["name"]:
        notes.append("no name in the draft; FCL has *%s*" % info["name"])
    if info["cite"] and parse_neutral(info["cite"]):
        own = render(parse_neutral(info["cite"]))
        if own != result["citation"]:
            notes.append("FCL records this judgment's citation as %s" % own)
    if entry.get("court"):
        outcome = court_check(entry["court"], c["court"])
        if outcome == "conflict":
            problems.append("draft calls the court '%s' but this is a %s citation"
                            % (entry["court"], c["court"]))
        elif outcome == "unknown":
            notes.append("court '%s' not recognised, so not compared" % entry["court"])
        if outcome != "unknown":
            checked.append("court")
    if entry.get("date"):
        given = parse_date(entry["date"])
        if given is None:
            notes.append("date '%s' not understood; FCL has %s" % (entry["date"], info["date"]))
        elif info["date"]:
            checked.append("date")
            if given != info["date"]:
                problems.append("date: draft %s, FCL %s" % (given, info["date"]))
    if info["date"] and info["date"][:4].isdigit() and int(info["date"][:4]) != c["year"]:
        notes.append("citation year %d but judgment dated %s" % (c["year"], info["date"]))
    wanted = parse_paras(entry.get("paras"))
    if wanted:
        if not info["paras"]:
            notes.append("paragraph numbers are not machine-readable in this judgment; "
                         "check the pinpoint by eye")
        else:
            top = max(info["paras"])
            quoted = [n for n in wanted if n not in info["paras"] and n in info["strays"]]
            missing = [n for n in wanted if n not in info["paras"] and n not in info["strays"]]
            present = [n for n in wanted if n in info["paras"]]
            if missing:
                problems.append("no paragraph %s; numbered paragraphs run to [%d]"
                                % (", ".join("[%d]" % n for n in missing), top))
            if quoted:
                problems.append("paragraph %s appears only out of sequence, probably inside "
                                "quoted material; check by eye"
                                % ", ".join("[%d]" % n for n in quoted))
            for bad in unchecked_ranges(entry.get("paras")):
                problems.append("range %s not checked in full (reversed, or wider than %d "
                                "paragraphs)" % (bad, MAX_RANGE))
            if present:
                checked.append("%d pinpoint%s%s" % (
                    len(present), "" if len(present) == 1 else "s",
                    " (sub-paragraphs checked only to the paragraph)"
                    if has_subparagraphs(entry.get("paras")) else ""))
            repeated = sorted(set(n for n in wanted if n in info["repeated"]))
            if repeated:
                notes.append("paragraph number %s occurs more than once; first one shown"
                             % ", ".join("[%d]" % n for n in repeated))
            result["pinpoints"] = [(n, snippet(info["paras"][n])) for n in wanted
                                   if n in info["paras"]]
    result["verdict"] = MISMATCH if problems else VERIFIED
    result["checked"] = "; ".join(([", ".join(checked)] if checked else []) + notes)
    result["detail"] = "; ".join(problems)


def check_one(entry, fetcher, probe=True):
    """Check one entry. A non-standard citation form is always reported."""
    result = _check_one(entry, fetcher, probe)
    form_note = result.pop("form_note", None)
    if form_note:
        if result["verdict"] == VERIFIED:
            result["verdict"] = MISMATCH
        result["detail"] = "; ".join(x for x in (form_note, result["detail"]) if x)
    return result


def _check_one(entry, fetcher, probe=True):
    raw = str(entry.get("citation", "")).strip()
    result = {"citation": raw, "name": entry.get("name") or "", "verdict": None,
              "detail": "", "checked": "", "link": "", "pinpoints": []}
    c = parse_neutral(raw)
    if not c:
        typo = mistyped_court(raw)
        if typo:
            result["verdict"] = MALFORMED
            result["detail"] = typo
        elif REPORT_RE.search(raw):
            result["verdict"] = LAW_REPORT
            result["detail"] = ("law-report citation: Find Case Law resolves neutral "
                                "citations only, so check this one manually")
            unchecked = parse_paras(entry.get("paras"))
            if unchecked:
                result["detail"] += "; pinpoint %s not checked" % ", ".join(
                    "[%d]" % n for n in unchecked)
        else:
            result["verdict"] = MALFORMED
            result["detail"] = "not recognised as a neutral citation or a law-report citation"
        return result
    result["citation"] = render(c) if (c["court"] != "EWCA" or c["pre"]) else c["text"]
    if c["nonstandard"]:
        result["citation"] = c["text"]
        result["form_note"] = "non-standard citation form: the standard form is %s" % render(c)
    addressable = PLAIN_COURTS + list(DIVISIONS) + ["EWCA"]
    if c["court"] not in addressable:
        code = c["court"]
        close = [k for k in addressable + list(NOT_ON_FCL)
                 if len(k) >= 4 and k != code and _near(code.upper(), k.upper())]
        if code not in NOT_ON_FCL and close:
            result["verdict"] = MALFORMED
            result["detail"] = ("'%s' is not a court code Find Case Law uses, and it is very "
                                "close to %s, so check for a typing error. If the code is "
                                "right, check BAILII or a law report" % (code, close[0]))
            return result
        result["verdict"] = OUTSIDE
        result["detail"] = ("Find Case Law has no address for %s citations%s, so this check "
                            "cannot look them up. That says nothing about whether the case is "
                            "real; check BAILII or a law report"
                            % (code, " (%s)" % NOT_ON_FCL[code] if code in NOT_ON_FCL else ""))
        return result
    slug, problem = slug_for(c)
    known_div = (c["court"] not in DIVISIONS or not c["div"]
                 or _canon(c["div"], DIVISIONS[c["court"]]))
    if slug:
        result["link"] = "%s/%s" % (FCL, slug)
        status, body = fetcher.get("%s/%s/data.xml" % (FCL, slug))
        if status == 200:
            info = read_judgment(body)
            if info is None:
                result["verdict"] = NOT_CHECKED
                result["detail"] = "Find Case Law returned a page that could not be read as XML"
                return result
            _compare(entry, c, info, result)
            return result
        if status == 404:
            page_status, _ = fetcher.get("%s/%s" % (FCL, slug), method="HEAD")
            if page_status == 200:
                result["verdict"] = NOT_CHECKED
                result["detail"] = ("Find Case Law has a page at this address but no "
                                    "machine-readable text; open the link and check by eye")
                return result
            status = 404 if page_status in (404, 200) else page_status
        if status != 404:
            result["verdict"] = NOT_CHECKED
            reason = body.decode("utf-8", "replace") if status == 0 else "HTTP %d" % status
            result["detail"] = "could not reach Find Case Law (%s); open the link to check" % reason
            return result
    # No judgment at the cited address, or no address could be built.
    if probe and not fetcher.offline:
        cited_link = "%s/%s" % (FCL, slug) if slug else ""
        form_fault = problem or (None if known_div else
                                 "(%s) is not a recognised %s division" % (c["div"], c["court"]))
        hits, failed = [], None
        for other, div in sibling_slugs(c):
            status, body = fetcher.get("%s/%s/data.xml" % (FCL, other))
            if status == 404:
                continue
            if status != 200:
                failed = "HTTP %d" % status if status else body.decode("utf-8", "replace")
                break
            info = read_judgment(body) or {"name": None}
            fcl_name = info.get("name") or "(name not recorded)"
            score = name_score(entry["name"], fcl_name) if entry.get("name") else None
            hits.append((score, other, render(c, div=div), fcl_name))
            if score == 1:
                break
        full = [h for h in hits if h[0] == 1]
        if full:
            # The same case under another division: the draft's citation is wrong.
            _, other, held_as, fcl_name = full[0]
            result["verdict"] = MISMATCH
            result["link"] = "%s/%s" % (FCL, other)
            result["checked"] = name_label(entry["name"])
            result["detail"] = "%s: FCL holds *%s* as %s" % (
                form_fault or "wrong court or division", fcl_name, held_as)
            return result
        if failed:
            # Never turn an unfinished lookup into a finding.
            result["verdict"] = NOT_CHECKED
            result["link"] = cited_link
            result["detail"] = ("nothing at the cited address, and the check of this court's "
                                "other divisions could not be finished (%s); open the link "
                                "to check" % failed)
            return result
        if hits:
            # Anything short of a full name match is only a lead.
            leads = "; ".join("*%s* %s" % (h[3], h[2]) for h in hits[:3])
            if not entry.get("name"):
                tail = ("FCL holds %s under that year and number, which is your case only "
                        "if the name matches" % leads)
            elif any(h[0] is not None and h[0] >= 0.5 for h in hits):
                tail = ("FCL holds %s under that year and number, and the name only partly "
                        "matches, so confirm whether it is the same case" % leads)
            else:
                tail = "that year and number belong to a different case: %s" % leads
            result["link"] = cited_link
            if form_fault:
                result["verdict"] = MALFORMED
                result["detail"] = "%s; %s" % (form_fault, tail)
            else:
                result["verdict"] = NOT_FOUND
                result["detail"] = ("no judgment at the cited address; %s. This is the result a "
                                    "fabricated citation would also get; check BAILII" % tail)
            return result
    if not slug or not known_div:
        result["verdict"] = MALFORMED
        result["detail"] = problem or ("(%s) is not a %s division or chamber that Find Case "
                                       "Law recognises, and nothing was found under that "
                                       "year and number" % (c["div"], c["court"]))
        if fetcher.offline and slug:
            result["verdict"] = NOT_CHECKED
            result["detail"] = "(%s) is not a recognised %s division; not checked online" % (
                c["div"], c["court"])
        return result
    if fetcher.offline:
        result["verdict"] = NOT_CHECKED
        result["detail"] = "not checked online; open the link to check"
        return result
    key = "/".join(slug.split("/")[:-2])
    earliest = EARLIEST.get(key)
    if earliest is None or c["year"] < earliest:
        result["verdict"] = OUTSIDE
        result["link"] = ""
        result["detail"] = (
            ("Find Case Law's earliest judgment from this court is from %d" % earliest
             if earliest else "Find Case Law's court list shows no holdings for this court")
            + " (court list read %s); its absence says nothing about whether the case is "
              "real, so check BAILII or a law report" % COVERAGE_READ)
        return result
    result["verdict"] = NOT_FOUND
    result["detail"] = ("no judgment at this address, though Find Case Law holds this court "
                        "from %d. Not proof of fabrication, because coverage is incomplete, "
                        "but it is the result a fabricated citation would also get; "
                        "check BAILII" % earliest)
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def report(results, offline=False, snippets="auto"):
    rows = sorted(enumerate(results), key=lambda r: (ORDER.index(r[1]["verdict"]), r[0]))
    lines = ["| Citation | Case name as written | Verdict | What didn't match | Checked | FCL link |",
             "|---|---|---|---|---|---|"]
    for _, r in rows:
        link = "[open](%s)" % r["link"] if r["link"] else ""
        lines.append("| %s | %s | **%s** | %s | %s | %s |" % (
            _cell(r["citation"]), _cell(r["name"]), r["verdict"], _cell(r["detail"]),
            _cell(r.get("checked", "")), link))
    pins = [(r, n, s) for _, r in rows for n, s in r.get("pinpoints", [])]
    if pins and (snippets == "all" or (snippets == "auto" and len(pins) <= SNIPPET_LIMIT)):
        lines += ["", "**Pinpoints found** (opening words, so you can see it is the right passage):", ""]
        for r, n, s in pins:
            lines.append("- %s at [%d]: “%s”" % (r["citation"], n, s))
    elif pins and snippets != "none":
        lines += ["", "**Pinpoints found:** %d paragraph numbers exist as cited (%s). Opening words "
                  "are shown only when there are %d or fewer."
                  % (len(pins), "; ".join(
                      "%s: %d" % (r["citation"], len(r["pinpoints"]))
                      for _, r in rows if r.get("pinpoints")), SNIPPET_LIMIT)]
    labels = {VERIFIED: "verified", MISMATCH: "mismatch", NOT_FOUND: "not found",
              MALFORMED: "malformed", OUTSIDE: "outside coverage",
              LAW_REPORT: "law report", NOT_CHECKED: "not checked"}
    counts = ["%d %s" % (sum(1 for r in results if r["verdict"] == v), labels[v])
              for v in [VERIFIED] + ORDER[:-1] if any(r["verdict"] == v for r in results)]
    total = len(results)
    today = datetime.date.today().strftime("%d %B %Y").lstrip("0")
    lines += ["", "%d citation%s: %s." % (total, "" if total == 1 else "s", ", ".join(counts))]
    if offline:
        lines.append("Nothing was checked online. Open each link and confirm the case name, "
                     "court, date and paragraph yourself.")
    else:
        lines.append("Checked against Find Case Law on %s. This confirms that each judgment "
                     "exists and that its details match; it does not check that a paragraph "
                     "supports the proposition it is cited for. %s" % (today, ATTRIBUTION))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def _read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:4] == b"PK\x03\x04" or data[:5] == b"%PDF-" or b"\x00" in data[:2048]:
        sys.exit("%s is not plain text (it looks like a Word, PDF or other binary file). "
                 "Convert it to text first. No citations were read." % path)
    return data.decode("utf-8", "replace")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check neutral citations against Find Case Law.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_scan = sub.add_parser("scan", help="list the citations in a text file")
    p_scan.add_argument("file")
    p_check = sub.add_parser("check", help="check a JSON list of citations")
    p_check.add_argument("file")
    p_check.add_argument("--offline", action="store_true",
                         help="build links and validate form without contacting Find Case Law")
    p_check.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p_check.add_argument("--snippets", choices=["auto", "all", "none"], default="auto",
                         help="show the opening words of each pinpointed paragraph "
                              "(auto: only when there are 12 or fewer)")
    p_check.add_argument("--no-probe", action="store_true",
                         help="do not look for the number under other divisions")
    args = parser.parse_args(argv)

    if args.command == "scan":
        text = _read(args.file)
        print(json.dumps({"citations": scan_text(text),
                          "paragraph_references": scan_paragraph_refs(text)},
                         indent=2, ensure_ascii=False))
        return 0

    try:
        entries = json.loads(_read(args.file))
    except ValueError as err:
        sys.exit("Could not read the citation list as JSON: %s" % err)
    if isinstance(entries, dict):
        entries = [entries]
    entries = [{"citation": e} if isinstance(e, str) else e for e in entries]
    fetcher = Fetcher(offline=args.offline)
    results = [check_one(e, fetcher, probe=not args.no_probe) for e in entries]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(report(results, offline=args.offline, snippets=args.snippets))
    verdicts = set(r["verdict"] for r in results)
    if NOT_CHECKED in verdicts:
        return 2
    return 1 if verdicts & {MISMATCH, NOT_FOUND, MALFORMED} else 0


if __name__ == "__main__":
    sys.exit(main())
