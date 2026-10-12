# Citation Preflight

An agent skill that checks every England and Wales neutral citation in a draft against the National Archives' [Find Case Law](https://caselaw.nationalarchives.gov.uk/) service (FCL) before the draft goes out. For each citation it reports whether the judgment exists and whether the details around it match, in a table that can be pasted into a note or an email.

It is for practitioners checking a skeleton argument, advice, blog post or piece of AI output before it goes out under their name. It takes about a minute for a typical draft.

## When to use it

Use it as the last step before a document that cites case law leaves your hands, and on anything an AI tool has drafted or researched for you. It answers one narrow question quickly: does every neutral citation point to a real judgment, with the right name, court and paragraph numbers? It suits a routine check on every draft, with a fuller audit kept for the documents that warrant one.

### Confidential and client material

An agent skill runs inside whichever AI service you use, and that service reads the whole draft. So the question of what you may check with this skill is really the question of what you may put into that service.

- **Personal subscriptions.** Most people use skills on a personal subscription to Claude or another general-purpose AI service. Client-confidential or privileged material should not be put into a consumer service of that kind. Use the skill there for work that carries no client confidence: published judgments and commentary, articles and blog posts, teaching materials, your own notes on the law, and AI-generated research that contains no client information.
- **Enterprise and organisational accounts.** Client documents such as skeleton arguments, advices and pleadings belong only in an environment with the data-protection safeguards your professional obligations require, typically an enterprise arrangement that your chambers, firm or organisation has approved for client material. Check your regulator's and your organisation's rules before relying on any such arrangement; this README is not advice on them.
- **Without an AI service at all.** The script works on its own. `scan` reads a file on your computer and sends nothing anywhere. `check` contacts Find Case Law only, and the only thing it sends is the address of each cited judgment. Nothing else in the draft leaves your machine. You then supply the case names and paragraph numbers yourself in a short list (see "How it works").

Whichever route you use, the citations themselves go to Find Case Law, a public service run by the National Archives. A list of the authorities in a draft can itself be sensitive in a live matter, so bear that in mind.

## What it checks

- **Existence.** The neutral citation resolves to a judgment on FCL.
- **Case name.** The name in the draft matches the name FCL holds. Short forms pass (*Montgomery* for *Montgomery v Lanarkshire Health Board*) and are marked "name (short form)" in the report. Initials count alongside a matching word (*Bailey v MoD*) but never by themselves.
- **Court and division.** A citation with the wrong division, such as `(KB)` for a judgment that is `(Admin)`, is reported with the citation FCL actually holds, provided the case name matches in full. Without a full match the other judgment is mentioned only as a lead, and the verdict stays "Not found on FCL".
- **Date.** Where the draft gives a judgment date, it is compared with FCL's.
- **Pinpoints.** Each paragraph number cited exists in the judgment. For up to 12 pinpoints the opening words of each paragraph are shown, so the reader can see it is the right passage. Paragraphs of another judgment quoted inside the one cited do not count, and a number that appears only out of sequence is reported for checking by eye.

Each row also says which of these were checked, so a judgment verified on its name alone is not mistaken for one verified on name, date and pinpoints.

## What it does not check

- Whether a case supports the proposition it is cited for, or is still good law. That needs a person, or a fuller audit such as [proposition-audit](https://github.com/banterny/proposition-audit).
- Quotations and statutory references.
- Sub-paragraphs: `[207(ii)]` is checked only as far as paragraph 207.
- Unmarked quotations at the very end of a judgment. Quoted paragraphs are normally marked as such in FCL's text and ignored. One that is not marked is still recognised where the judgment's own numbering resumes after it, but not if it is the last thing in the document.
- Cases the draft names without a neutral citation. The skill lists them as not checked and does not supply a citation.
- Law-report citations (`[1957] 1 WLR 582`). FCL resolves neutral citations only, so these are listed as "Not checkable here" and never as failures.
- Anything FCL cannot look up by citation, such as the House of Lords and the Scottish courts, and years before a court's first holding.

## Verdicts

| Verdict | Meaning |
|---|---|
| Verified | The judgment is on FCL and every detail supplied matches. |
| Mismatch | The judgment is on FCL but the name, court or division, date or a pinpoint differs. |
| Not found on FCL | A well-formed citation with nothing at its address, for a court and year FCL does hold. Not proof of fabrication, because FCL is incomplete, but a fabricated citation gets the same result. |
| Malformed | Not a valid neutral citation: a court code that is a near miss for a real one, a missing division, or a division that court does not have. |
| Outside coverage | FCL has no address for that court's citations, or holds nothing from that court for that year. The check says nothing about whether the case is real. |
| Not checkable here | A law-report citation. |
| Not checked | FCL could not be reached, or it has no machine-readable text for the judgment. Never a finding. |

## How it works

The agent reads the draft and lists each citation with the case name and pinpoints attached to it. Deciding which judgment a bare "[66]" belongs to is the one step that needs reading, and where the draft leaves it unclear the paragraph is left out and listed in a note. A script, `scripts/citation_preflight.py`, does the rest: it works out each judgment's FCL address, fetches the judgment's XML, compares the details and prints the table. Because a script does the comparing, the same draft gives the same result each time.

The script needs Python 3.9 or later and nothing else. It contacts one host, `caselaw.nationalarchives.gov.uk`, at no more than one request a second, and only for the judgments the draft cites. Where nothing is at a citation's address, it also tries the same year and number under that court's other divisions (up to 13 further addresses for a High Court citation) to tell a wrong division from a missing judgment. It keeps no log and sends nothing anywhere else.

Where the session has no Python or cannot reach FCL, the skill still lists and validates every citation and gives a checklist of links to open by hand. It never guesses a verdict it could not check.

The script can also be used on its own:

```bash
python3 scripts/citation_preflight.py scan draft.txt
python3 scripts/citation_preflight.py check list.json
python3 scripts/citation_preflight.py check --offline list.json
```

`list.json` is a list of entries such as `{"citation": "[2015] UKSC 11", "name": "Montgomery", "paras": [87]}`.

## Installation

### Claude Code

```bash
git clone https://github.com/banterny/citation-preflight.git ~/.claude/skills/citation-preflight
```

### Claude.ai and the Claude desktop app's Chat mode

Download the repository as a ZIP, rename the unzipped folder to `citation-preflight`, zip it again so that the ZIP contains `citation-preflight/SKILL.md`, and upload it under Customize → Skills. Code execution must be switched on. If the session cannot reach FCL, the skill falls back to the checklist of links.

### Other agents

The skill follows the open Agent Skills format. Copy or link the folder into the agent's skills directory.

## Sources checked

Each fact the skill relies on was checked at its primary source on 12 October 2026.

**Addresses.** FCL's [API documentation](https://nationalarchives.github.io/ds-find-caselaw-docs/public) says a neutral citation has a "slug" (`[2024] UKSC 123` gives `uksc/2024/123`) which "can be turned into a human-facing URL by appending it" to the site address. Confirmed by request for the Supreme Court, the Court of Appeal and four High Court divisions. King's Bench and Queen's Bench addresses are not interchangeable: `[2019] EWHC 936 (QB)` is at `/ewhc/qb/2019/936` and nothing is at `/ewhc/kb/2019/936`. The same documentation warns that identifiers "are not guaranteed to be unique to a single document".

**Machine-readable text.** Each judgment has an Akoma Ntoso XML version at `…/data.xml` carrying the case name, judgment date and citation. Paragraph numbering is not uniform. Recent judgments give each paragraph an identifier; *Montgomery* [2015] UKSC 11 has none and numbers its 117 paragraphs only in the text. Paragraphs quoted from other judgments sit inside the XML with their own numbers. The script reads the numbers from the document's structure and ignores quoted material.

**Court table.** The court codes and address patterns come from the National Archives' own [ds-caselaw-utils](https://github.com/nationalarchives/ds-caselaw-utils) (MIT licence; version 5.1.0, 28 September 2026). The package needs Python 3.12 and third-party libraries, so the skill restates its patterns instead of depending on it. A division FCL adds later is still tried at its address.

**Coverage.** FCL's [court list](https://caselaw.nationalarchives.gov.uk/courts-and-tribunals) says: "Coverage within that range may not be complete — not every judgment is sent to us for publication." Its earliest holdings are 2009 for the Supreme Court and Privy Council, 2001 for the Court of Appeal (Civil Division), 2003 for the Criminal Division and most High Court divisions, 2014 for the Family Court and 2021 for the Employment Appeal Tribunal. It lists no House of Lords judgments. The script's copy of these years is dated, and a citation from before a court's listed start is still looked up in case FCL has since added it.

**Rate limit.** FCL allows "up to 1,000 requests (of any type) … in any rolling five minute period per IP address". The script makes at most one a second and stops if it is told to slow down.

**Licence.** FCL content is under the [Open Justice Licence v2.0](https://caselaw.nationalarchives.gov.uk/open-justice-licence), which does not cover "computational analysis of the Information (including indexing by search engines)". FCL [defines](https://caselaw.nationalarchives.gov.uk/when-you-need-permission) that as "using automated or algorithmic methods to process large numbers of judgments systematically — including using AI or large language models (LLMs)", and lists "downloading judgments one at a time as you need them" among the uses that need no licence. A licence is needed for "any programmatic searching in bulk across Find Case Law records to identify, extract or enrich contents within the records". This skill fetches only the judgments one document cites and searches nothing, which the author takes to be on the permitted side. It must not be looped over a collection of documents or used to gather judgments. Anyone unsure about their own use can ask caselawlicence@nationalarchives.gov.uk.

**Courts with no citation address.** The script keeps no list of its own of courts that FCL lacks. Any court code that is not in the National Archives' citation table has no FCL address, so it is reported as "Outside coverage" whatever the court. Three codes are named in the message: UKHL (House of Lords), CSIH and CSOH (Court of Session). Each was confirmed in use in *Montgomery* [2015] UKSC 11, which cites [2004] UKHL 41, [2013] CSIH 3 and [2010] CSOH 104. A code that is a near miss for a real one (one letter wrong, or two swapped) is reported as "Malformed", with a note to check for a typing error.

## Review

Before release the script was reviewed adversarially by a second AI model (OpenCode's review command) with a brief to find false "Verified" and false "Not found" results. It raised six findings; all were acted on, except that single-surname short forms still pass, by design, and are labelled in the report.

## Related work

[uk-citation-verification](https://lawve.ai/@matei-clej/skill/uk-citation-verification) by Matei Clej (MIT) checks UK citations against FCL and also checks quotations and statutes, which this skill does not. The separate "Outside coverage" verdict here follows the approach of that skill. Citation Preflight was written independently and shares no text or code with it; it differs in taking the case name and pinpoints from the draft for every citation, detecting a wrong division, and producing a single table.

[proposition-audit](https://github.com/banterny/proposition-audit) is the broader companion, and is not a citation checker. It audits every claim in a piece of AI output: empirical facts, citations, legal propositions and interpretive argument. It classifies each claim by type and by how much the argument depends on it, checks it against sources suited to its field, scores how far the sources support it, and assesses whether opposing positions are presented fairly. That depth takes longer, so the two are designed to be used together: this skill on every draft, proposition-audit where the substance needs testing.

## Tests

```bash
python3 -m unittest discover tests
```

The tests use canned responses and make no network requests.

## Disclaimer

This skill supports the user's professional judgement; it does not replace it. A clean result means the citations resolve and their details match. It is not a substitute for reading the judgments.

## Licence

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Output of the skill contains information licensed under the Open Justice Licence v2.0.

## Author

Anthony Searle, barrister at the English Bar. GitHub: [@banterny](https://github.com/banterny)
