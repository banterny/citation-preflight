---
name: citation-preflight
description: Checks every England and Wales neutral citation in a draft against the National Archives' Find Case Law before the draft goes out. Confirms that each judgment exists, that the case name, court, division and date match, and that each pinpoint paragraph exists, then returns a paste-ready table with the problems first. Use when asked to check citations, preflight a draft, check the authorities in a skeleton argument, advice, blog post or AI output, confirm that cited cases are real, or check a neutral citation or pinpoint. This is a fast mechanical check. It does not judge whether a case supports the proposition it is cited for (use proposition-audit for that), and it does not check quotations, statutes or law-report citations.
license: Apache-2.0
compatibility: Needs Python 3.9 or later and network access to caselaw.nationalarchives.gov.uk. Without either, it produces a checklist of links to check by hand.
metadata:
  author: Anthony Searle
  version: "2026.10.12"
---

# Citation Preflight

Check each neutral citation in a draft against Find Case Law (FCL) and report whether it resolves and whether its details match. The check is mechanical: a script does the looking up and comparing, and its output is the report.

## Rules that hold throughout

- **Every verdict comes from the script.** Never give, change or soften a verdict from memory, and never supply a "correct" citation, case name or paragraph from memory. The only corrections offered are the ones FCL returned.
- **Stay mechanical.** Do not comment on the law, on whether a case supports its proposition, or on the drafting, and do not rewrite the draft. If the user then asks for that, point them to `proposition-audit`.
- **"Not found on FCL" is not "fabricated".** Never call a case fake, invented or non-existent. Use the script's wording.
- **Fetch only what the draft cites.** The script fetches one judgment per citation. Do not search FCL, crawl it, try other sites, or download judgments the draft does not cite.

## Steps

1. **Get the draft as plain text.** A text or Markdown file can be scanned where it is; the script only reads it. Save pasted text to a temporary file. Convert a Word or PDF file to text first. If the file cannot be read, say so and stop: an unreadable file is never "no citations found". Front matter and footnotes are part of the draft.

2. **List the citations.** The script is in this skill's folder; give the draft's full path:

   ```bash
   python3 scripts/citation_preflight.py scan /path/to/draft.txt
   ```

   It prints JSON with two lists: `citations` (every neutral and law-report citation, with line numbers and surrounding words) and `paragraph_references` (every paragraph reference, line by line).

3. **Build the check list.** Write a JSON file with one entry per citation in `citations`, law reports included:

   ```json
   [{"citation": "[2015] UKSC 11",
     "name": "Montgomery v Lanarkshire Health Board",
     "paras": [87, "89-91", "107(ii)"],
     "court": "Supreme Court",
     "date": "11 March 2015"}]
   ```

   - `name`: the case name the draft attaches to that citation, as written but without Markdown markers. If the draft uses more than one form, take the fullest. Leave it out if the draft gives none.
   - `paras`: every paragraph the draft cites **in that judgment**, wherever in the draft it appears. Numbers and ranges can be copied as written, brackets and dashes included; repeats do no harm. Leave it out if there are none.
   - `court`: only where the draft names the court, in the draft's words ("Court of Appeal", "CA").
   - `date`: only where the draft gives the judgment date ("11 March 2015" or "2015-03-11").

   Work through `paragraph_references` and assign each one. Attach a paragraph to a citation only where the draft attributes it to that judgment:
   - A later short reference ("*Montgomery* at [87]", "the court returned to this at [90]") belongs to the judgment cited earlier.
   - In a note about one judgment, bare references such as "[66]" usually mean that judgment, even straight after another case's name ("applying *Bailey* [306]" in a summary of a different case). The exception is a number the draft elsewhere attributes to the other case ("per Lord Nicholls at [32]").
   - Paragraphs of a lower court's judgment quoted on appeal ("the judge at [93]") are not paragraphs of the appeal judgment. Leave them out.
   - Paragraphs of a statute, report or other document are not pinpoints. Leave them out.
   - A number the draft uses for two judgments goes in both entries.
   - Where the judgment is unclear, leave the paragraph out.

4. **Run the check.**

   ```bash
   python3 scripts/citation_preflight.py check /path/to/list.json
   ```

   Exit code 0 means nothing to report, 1 means problems were found, and 2 means some rows could not be checked. All three are completed runs. Confirm that every entry in `citations` has a row; if one is missing, add it and run the check again.

5. **Report.** Give the script's output exactly as printed, with nothing before it. Rows are sorted with problems first and Verified last. Then add a **Notes** list for whichever of these apply, and leave it out if none do:
   - cases the draft names without a neutral citation, with any pinpoints to them: not checked. Do not supply the citation;
   - paragraph references left out in step 3, with the reason (lower court's paragraph, judgment unclear);
   - paragraph references attached to a judgment by inference. In a note about one judgment, say once that bare references were read as that judgment's, and itemise only those sitting beside another case's name;
   - a "name partly differs" row where the difference looks like an abbreviation or an omitted party (say so; the verdict stays);
   - rows marked "Not checked", with the reason.

   With more than 12 pinpoints the script reports a count and omits the opening words. If the user asks for them, run the check again with `--snippets all`.

## Verdicts

| Verdict | Meaning |
|---|---|
| Verified | The judgment is on FCL and every detail supplied matches. |
| Mismatch | The judgment is on FCL but the name, court or division, date or a pinpoint differs. The row says which, and what FCL holds. |
| Not found on FCL | A well-formed citation with nothing at its address, for a court and year FCL does hold. FCL's coverage is incomplete, so this is not proof of fabrication, but a fabricated citation gets the same result. |
| Malformed | Not a valid neutral citation: a court code that is a near miss for a real one, a missing division, or a division that court does not have. |
| Outside coverage | FCL has no address for that court's citations (the House of Lords and the Scottish courts, for example), or holds nothing from that court for that year. The check says nothing about whether the case is real. |
| Not checkable here | A law-report citation. FCL resolves neutral citations only. |
| Not checked | The script could not reach FCL, or FCL has no machine-readable text for the judgment. Never a finding. |

## When the script cannot run or cannot reach FCL

- **FCL unreachable:** the affected rows come back "Not checked" with their links. Report them as they are. `check --offline list.json` produces the whole table that way without trying.
- **No Python or no shell:** build each link by hand from the address rules below, give every neutral citation the verdict "Not checked", and present the same table as a checklist of links for the user to open. Do not open the pages and judge them yourself.

| Citation form | Address after `https://caselaw.nationalarchives.gov.uk/` |
|---|---|
| `[2015] UKSC 11` (also UKPC, EWCOP, EWFC, EWCC, EWCR, EAT) | `uksc/2015/11` |
| `[2014] EWCA Civ 906` (or Crim) | `ewca/civ/2014/906` |
| `[2019] EWHC 936 (QB)` (any High Court division) | `ewhc/qb/2019/936` |
| `[2022] UKUT 5 (IAC)` (also UKFTT chambers) | `ukut/iac/2022/5` |
| `[2024] EWCOP 7 (T3)`, `[2024] EWFC 12 (B)` | `ewcop/t3/2024/7`, `ewfc/b/2024/12` |

## Example

Draft (the *Smith v Jones* citation was made up for this example):

> The duty is stated in *Montgomery v Lanarkshire Health Board* [2015] UKSC 11 at [87]. In *Bilal v St George's University Hospital NHS Foundation Trust* [2023] EWCA Civ 605 at [93] the Court of Appeal applied it, as did *Smith v Jones* [2024] EWHC 999 (KB), following *Bolam v Friern Hospital Management Committee* [1957] 1 WLR 582.

Report, as the script printed it on 12 October 2026:

| Citation | Case name as written | Verdict | What didn't match | Checked | FCL link |
|---|---|---|---|---|---|
| [2023] EWCA Civ 605 | Bilal v St George's University Hospital NHS Foundation Trust | **Mismatch** | no paragraph [93]; numbered paragraphs run to [70] | name, court | [open](https://caselaw.nationalarchives.gov.uk/ewca/civ/2023/605) |
| [2024] EWHC 999 (KB) | Smith v Jones | **Not found on FCL** | no judgment at this address, though Find Case Law holds this court from 2003. Not proof of fabrication, because coverage is incomplete, but it is the result a fabricated citation would also get; check BAILII |  | [open](https://caselaw.nationalarchives.gov.uk/ewhc/kb/2024/999) |
| [1957] 1 WLR 582 | Bolam v Friern Hospital Management Committee | **Not checkable here** | law-report citation: Find Case Law resolves neutral citations only, so check this one manually |  |  |
| [2015] UKSC 11 | Montgomery v Lanarkshire Health Board | **Verified** |  | name, 1 pinpoint | [open](https://caselaw.nationalarchives.gov.uk/uksc/2015/11) |

**Pinpoints found** (opening words, so you can see it is the right passage):

- [2015] UKSC 11 at [87]: “The correct position, in relation to the risks of injury involved in treatment, can now be seen to be substantially that adopted in Sidaway by Lord…”

4 citations: 1 verified, 1 mismatch, 1 not found, 1 law report.
Checked against Find Case Law on 12 October 2026. This confirms that each judgment exists and that its details match; it does not check that a paragraph supports the proposition it is cited for. Contains information licensed under the Open Justice - Licence v2.0.

## Limitations

- **One source.** Only FCL is consulted. It holds most senior courts from 2001 to 2003 onwards, holds nothing from the House of Lords, and is incomplete within its ranges.
- **Existence is not authority.** A Verified row means the judgment exists and the details match. It says nothing about what the case decided, whether the paragraph supports the proposition, or whether the case is still good law.
- **Not checked at all:** quotations, statutes, law-report citations and their pinpoints, cases named without a neutral citation, and paragraph references whose judgment the draft leaves unclear.
- **Pinpoints.** Sub-paragraphs such as [207(ii)] are checked only as far as paragraph [207]. A range wider than 200 paragraphs is reported, not checked. A quotation that FCL's text does not mark as one is recognised only where the judgment's own numbering resumes after it. A few older judgments have no machine-readable paragraph numbers; the row then says to check by eye. Where a number occurs twice in a judgment (an appendix, for example), the first is shown.
- **Names** are compared word by word. A single surname matches any case at that citation with a party of that name, and is marked "name (short form)". Initials alone never match. An unusual short form can show as "name partly differs".
- **Wrong division.** The script reports a wrong division only where the name matches in full. Otherwise a judgment found under another division is given as a lead and the verdict stays "Not found on FCL".
- **Licence.** FCL content is used under the Open Justice Licence, which does not cover computational analysis across large numbers of judgments. Run this on the citations in a document, one document at a time. Do not loop it over a collection of documents or use it to gather judgments.
