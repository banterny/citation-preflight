"""Offline tests for scripts/citation_preflight.py. No network is used.

Run from the skill folder:  python3 -m unittest discover tests

The citations in this file are fixtures for testing citation forms. They are
not offered as real authorities and most were not checked against any source.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import citation_preflight as cp  # noqa: E402

XML = """<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
 xmlns:uk="https://caselaw.nationalarchives.gov.uk/akn">
<judgment><meta><identification><FRBRWork>
<FRBRdate date="2020-02-03" name="judgment"/>
<FRBRname value="Alpha &amp; Ors v Beta Health Authority"/>
</FRBRWork></identification>
<proprietary><uk:cite>[2020] EWHC 1 (QB)</uk:cite></proprietary></meta>
<judgmentBody><decision>
<paragraph eId="para_1"><num>1.</num><content><p>First paragraph text.</p></content></paragraph>
<paragraph><num style="x">2.</num><content><p>Second paragraph, which quotes:</p>
<block><embeddedStructure><paragraph><num>93.</num><content><p>Quoted from below.</p></content></paragraph></embeddedStructure></block>
</content></paragraph>
<paragraph eId="para_3"><num>3.</num><content><p>Third.</p></content></paragraph>
<paragraph eId="para_3b"><num>3.</num><content><p>Third again, in an appendix.</p></content></paragraph>
</decision></judgmentBody></judgment></akomaNtoso>""".encode()


class FakeFetcher:
    """Serves canned answers in place of Find Case Law."""

    offline = False

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def get(self, url, method="GET"):
        self.asked.append(url)
        return self.pages.get(url, (404, b""))


def url(slug):
    return cp.FCL + "/" + slug + "/data.xml"


class Addresses(unittest.TestCase):
    def slug(self, text):
        return cp.slug_for(cp.parse_neutral(text))[0]

    def test_addresses(self):
        self.assertEqual(self.slug("[2015] UKSC 11"), "uksc/2015/11")
        self.assertEqual(self.slug("[2014] EWCA Civ 906"), "ewca/civ/2014/906")
        self.assertEqual(self.slug("[2019] EWHC 936 (QB)"), "ewhc/qb/2019/936")
        self.assertEqual(self.slug("[2025] EWHC 1383 (Admin)"), "ewhc/admin/2025/1383")
        self.assertEqual(self.slug("[2022] UKUT 5 (IAC)"), "ukut/iac/2022/5")
        self.assertEqual(self.slug("[2024] EWCOP 7 (T3)"), "ewcop/t3/2024/7")
        self.assertEqual(self.slug("[2024] EWFC 12 (B)"), "ewfc/b/2024/12")
        self.assertEqual(self.slug("[2024] EWFC 12"), "ewfc/2024/12")
        self.assertEqual(self.slug("[2020] EAT 17"), "eat/2020/17")

    def test_old_order_and_spacing(self):
        self.assertEqual(self.slug("[2001] EWHC Admin 123"), "ewhc/admin/2001/123")
        self.assertEqual(self.slug("[2019] EWHC  936 (QB)"), "ewhc/qb/2019/936")

    def test_bracketed_word_after_plain_court_is_not_a_division(self):
        self.assertEqual(self.slug("[2015] UKSC 11 (Montgomery)"), "uksc/2015/11")

    def test_no_address(self):
        self.assertIsNone(self.slug("[2019] EWHC 936"))
        self.assertIsNone(self.slug("[2019] EWCA 936"))
        self.assertIsNone(self.slug("[2024] EHWC 999 (KB)") if cp.parse_neutral("[2024] EHWC 999 (KB)") else None)


class Scan(unittest.TestCase):
    def test_scan_kinds_and_lines(self):
        text = ("See *A v B* [2015] UKSC 11; [2015] AC 1430.\n"
                "Also [1957] 1 WLR 582 and (1980) 71 Cr App R 1, decided (2023) 12 July 2023.\n"
                "Again [2015] UKSC 11.")
        got = cp.scan_text(text)
        self.assertEqual([(g["citation"], g["kind"]) for g in got], [
            ("[2015] UKSC 11", "neutral"), ("[2015] AC 1430", "law report"),
            ("[1957] 1 WLR 582", "law report"), ("(1980) 71 Cr App R 1", "law report")])
        self.assertEqual(got[0]["lines"], [1, 3])


class Reading(unittest.TestCase):
    def test_reads_name_date_and_top_level_paragraphs_only(self):
        info = cp.read_judgment(XML)
        self.assertEqual(info["name"], "Alpha & Ors v Beta Health Authority")
        self.assertEqual(info["date"], "2020-02-03")
        self.assertEqual(sorted(info["paras"]), [1, 2, 3])
        self.assertEqual(info["repeated"], [3])
        self.assertEqual(info["paras"][1], "First paragraph text.")

    def test_refuses_entities(self):
        self.assertIsNone(cp.read_judgment(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>'))


class Sequence(unittest.TestCase):
    def numbers(self, xml_paragraphs):
        body = "".join("<paragraph><num>%d.</num><content><p>x</p></content></paragraph>" % n
                       for n in xml_paragraphs)
        xml = ('<akomaNtoso xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0"><judgment>'
               "<judgmentBody><decision>%s</decision></judgmentBody></judgment></akomaNtoso>" % body)
        info = cp.read_judgment(xml.encode())
        return sorted(info["paras"]), sorted(info["strays"]), info["repeated"]

    def test_unmarked_quotation_is_set_aside(self):
        self.assertEqual(self.numbers([1, 2, 93, 94, 3, 4]), ([1, 2, 3, 4], [93, 94], []))

    def test_numbering_that_skips_and_never_returns_is_kept(self):
        self.assertEqual(self.numbers([1, 2, 3, 20, 21, 22]), ([1, 2, 3, 20, 21, 22], [], []))
        self.assertEqual(self.numbers([1, 2, 4, 5]), ([1, 2, 4, 5], [], []))

    def test_restart_and_duplicate_are_repeats_not_strays(self):
        self.assertEqual(self.numbers([1, 2, 3, 1, 2]), ([1, 2, 3], [], [1, 2]))
        self.assertEqual(self.numbers([1, 2, 2, 3]), ([1, 2, 3], [], [2]))

    def test_pinpoint_to_a_stray_number_is_a_problem(self):
        info = {"name": None, "date": None, "cite": None, "paras": {1: "a", 2: "b"},
                "repeated": [], "strays": {93}}
        result = {"citation": "[2020] EWHC 1 (QB)"}
        cp._compare({"paras": [93]}, cp.parse_neutral("[2020] EWHC 1 (QB)"), info, result)
        self.assertEqual(result["verdict"], cp.MISMATCH)
        self.assertIn("out of sequence", result["detail"])


class Names(unittest.TestCase):
    def test_short_forms_and_initials(self):
        full = "Montgomery v Lanarkshire Health Board"
        self.assertEqual(cp.name_score("Montgomery", full), 1)
        self.assertEqual(cp.name_score("Montgomery v Lanarkshire HB", full), 1)
        self.assertEqual(cp.name_score("Bailey v MoD", "Bailey v Ministry of Defence & Anor"), 1)
        self.assertEqual(cp.name_score("Bilal v St George's", "Sidra Bilal & Anor v St George’s University Hospital NHS Foundation Trust"), 1)

    def test_different_case(self):
        self.assertEqual(cp.name_score("Mitchell v News Group Newspapers", "Denton & Ors v TH White Ltd & Ors"), 0)


class Verdicts(unittest.TestCase):
    def check(self, entry, pages):
        return cp.check_one(entry, FakeFetcher(pages))

    def test_verified_with_pinpoint(self):
        r = self.check({"citation": "[2020] EWHC 1 (QB)", "name": "Alpha v Beta HA", "paras": ["1-2"],
                        "date": "3 February 2020", "court": "High Court"},
                       {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.VERIFIED)
        self.assertEqual([n for n, _ in r["pinpoints"]], [1, 2])
        self.assertEqual(r["checked"], "name, court, date, 2 pinpoints")

    def test_found_and_missing_pinpoints_are_both_reported(self):
        r = self.check({"citation": "[2020] EWHC 1 (QB)", "paras": [1, 93, "2(ii)"]},
                       {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.MISMATCH)
        self.assertIn("no paragraph [93]", r["detail"])
        self.assertEqual(r["detail"], "no paragraph [93]; numbered paragraphs run to [3]")
        self.assertEqual(r["checked"], "2 pinpoints (sub-paragraphs checked only to the paragraph); "
                                       "no name in the draft; FCL has *Alpha & Ors v Beta Health Authority*")

    def test_pinpoint_on_a_law_report_is_reported_unchecked(self):
        r = self.check({"citation": "[2005] 2 AC 176", "paras": [32]}, {})
        self.assertEqual(r["verdict"], cp.LAW_REPORT)
        self.assertIn("pinpoint [32] not checked", r["detail"])

    def test_quoted_paragraph_number_is_not_a_pinpoint(self):
        r = self.check({"citation": "[2020] EWHC 1 (QB)", "paras": [93]},
                       {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.MISMATCH)
        self.assertIn("no paragraph [93]", r["detail"])

    def test_wrong_name_date_and_court(self):
        r = self.check({"citation": "[2020] EWHC 1 (QB)", "name": "Gamma v Delta",
                        "date": "2020-02-04", "court": "Court of Appeal"},
                       {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.MISMATCH)
        for part in ("different case", "date:", "Court of Appeal"):
            self.assertIn(part, r["detail"])

    def test_wrong_division_is_found(self):
        r = self.check({"citation": "[2020] EWHC 1 (KB)", "name": "Alpha v Beta"},
                       {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.MISMATCH)
        self.assertIn("[2020] EWHC 1 (QB)", r["detail"])

    def test_other_division_hit_without_a_name_is_only_a_lead(self):
        r = self.check({"citation": "[2020] EWHC 1 (KB)"}, {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.NOT_FOUND)
        self.assertIn("only if the name matches", r["detail"])
        self.assertEqual(r["link"], cp.FCL + "/ewhc/kb/2020/1")

    def test_other_division_hit_with_partial_name_is_only_a_lead(self):
        r = self.check({"citation": "[2020] EWHC 1 (KB)", "name": "Alpha v Gamma"},
                       {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.NOT_FOUND)
        self.assertIn("only partly matches", r["detail"])

    def test_every_division_is_tried_before_deciding(self):
        other = XML.replace(b"Alpha &amp; Ors v Beta Health Authority", b"Gamma v Delta")
        pages = {url("ewhc/qb/2020/1"): (200, other), url("ewhc/ch/2020/1"): (200, XML)}
        r = self.check({"citation": "[2020] EWHC 1 (KB)", "name": "Alpha v Beta HA"}, pages)
        self.assertEqual(r["verdict"], cp.MISMATCH)
        self.assertIn("[2020] EWHC 1 (Ch)", r["detail"])
        r = self.check({"citation": "[2020] EWHC 1 (KB)"}, pages)
        self.assertEqual(r["verdict"], cp.NOT_FOUND)
        self.assertIn("(QB)", r["detail"])
        self.assertIn("(Ch)", r["detail"])

    def test_failure_while_trying_other_divisions_is_never_a_verdict(self):
        for citation in ("[2024] EWHC 999 (KB)", "[2024] EWHC 12 (XYZ)", "[2024] EWHC 12"):
            for status in (0, 429, 500):
                r = self.check({"citation": citation}, {url("ewhc/qb/2024/" + citation.split()[2]): (status, b"timeout")})
                self.assertEqual(r["verdict"], cp.NOT_CHECKED, (citation, status))

    def test_non_standard_forms_are_looked_up_and_reported(self):
        r = self.check({"citation": "[2020] EWCA 1 (Civ)", "name": "Alpha v Beta HA"},
                       {url("ewca/civ/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.MISMATCH)
        self.assertEqual(r["citation"], "[2020] EWCA 1 (Civ)")
        self.assertIn("the standard form is [2020] EWCA Civ 1", r["detail"])
        r = self.check({"citation": "[2020] UKUT AAC 1"}, {url("ukut/aac/2020/1"): (200, XML)})
        self.assertIn("the standard form is [2020] UKUT 1 (AAC)", r["detail"])

    def test_wide_or_reversed_range_is_reported_not_dropped(self):
        for paras in (["1-500"], ["3-1"]):
            r = self.check({"citation": "[2020] EWHC 1 (QB)", "paras": paras},
                           {url("ewhc/qb/2020/1"): (200, XML)})
            self.assertEqual(r["verdict"], cp.MISMATCH, paras)
            self.assertIn("not checked in full", r["detail"])

    def test_initials_alone_do_not_verify_and_short_forms_are_labelled(self):
        pages = {url("ewhc/qb/2020/1"): (200, XML)}
        r = self.check({"citation": "[2020] EWHC 1 (QB)", "name": "BH"}, pages)
        self.assertEqual(r["verdict"], cp.MISMATCH)
        r = self.check({"citation": "[2020] EWHC 1 (QB)", "name": "Alpha"}, pages)
        self.assertEqual(r["verdict"], cp.VERIFIED)
        self.assertEqual(r["checked"], "name (short form)")

    def test_unknown_division_without_a_name_stays_malformed(self):
        r = self.check({"citation": "[2020] EWHC 1 (XYZ)"}, {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.MALFORMED)
        self.assertIn("not a recognised EWHC division", r["detail"])

    def test_number_used_by_another_case_is_not_found(self):
        r = self.check({"citation": "[2020] EWHC 1 (KB)", "name": "Smith v Jones"},
                       {url("ewhc/qb/2020/1"): (200, XML)})
        self.assertEqual(r["verdict"], cp.NOT_FOUND)
        self.assertIn("different case", r["detail"])

    def test_not_found_outside_coverage_and_malformed(self):
        self.assertEqual(self.check({"citation": "[2024] EWHC 999 (KB)"}, {})["verdict"], cp.NOT_FOUND)
        self.assertEqual(self.check({"citation": "[1999] EWCA Civ 5"}, {})["verdict"], cp.OUTSIDE)
        self.assertEqual(self.check({"citation": "[2004] UKHL 41"}, {})["verdict"], cp.OUTSIDE)
        self.assertIn("House of Lords", self.check({"citation": "[2004] UKHL 41"}, {})["detail"])
        for unlisted in ("[2010] CSIH 104", "[2005] UKSPC 123", "[2019] NICA 5", "[2019] HCJAC 7"):
            self.assertEqual(self.check({"citation": unlisted}, {})["verdict"], cp.OUTSIDE, unlisted)
        self.assertEqual(self.check({"citation": "[2024] EWHC 12 (XYZ)"}, {})["verdict"], cp.MALFORMED)
        self.assertEqual(self.check({"citation": "[2024] EWHC 12"}, {})["verdict"], cp.MALFORMED)
        self.assertEqual(self.check({"citation": "[2024] EHWC 12 (KB)"}, {})["verdict"], cp.MALFORMED)
        self.assertEqual(self.check({"citation": "[2014] ECWA Civ 906"}, {})["verdict"], cp.MALFORMED)
        self.assertEqual(self.check({"citation": "[2015] UKCS 11"}, {})["verdict"], cp.MALFORMED)
        for report in ("[1957] 1 WLR 582", "[2015] AC 1430", "[1987] QB 730", "[2005] 2 AC 176",
                       "(1980) 71 Cr App R 1", "[1998] AC 232", "[2003] ICR 337",
                       "[2019] Med LR 1", "[2004] EMLR 12", "[1999] Fam 1"):
            self.assertEqual(self.check({"citation": report}, {})["verdict"], cp.LAW_REPORT, report)

    def test_scan_lists_a_mistyped_court_as_neutral(self):
        got = cp.scan_text("See Smith v Jones [2024] EHWC 12 (KB) and [2015] AC 1430.")
        self.assertEqual([(g["citation"], g["kind"]) for g in got],
                         [("[2024] EHWC 12 (KB)", "neutral"), ("[2015] AC 1430", "law report")])

    def test_held_before_listed_start_year_still_verifies(self):
        r = self.check({"citation": "[1999] EWCA Civ 5"}, {url("ewca/civ/1999/5"): (200, XML)})
        self.assertEqual(r["verdict"], cp.VERIFIED)

    def test_failure_to_reach_site_is_never_a_verdict(self):
        for status in (0, 429, 500, 503):
            r = self.check({"citation": "[2020] EWHC 1 (QB)"}, {url("ewhc/qb/2020/1"): (status, b"down")})
            self.assertEqual(r["verdict"], cp.NOT_CHECKED, status)

    def test_offline_gives_links_and_no_verdicts(self):
        r = cp.check_one({"citation": "[2020] EWHC 1 (QB)"}, cp.Fetcher(offline=True))
        self.assertEqual(r["verdict"], cp.NOT_CHECKED)
        self.assertEqual(r["link"], cp.FCL + "/ewhc/qb/2020/1")

    def test_offline_run_exits_2(self):
        import contextlib
        import io
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump([{"citation": "[2020] EWHC 1 (QB)"}], handle)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cp.main(["check", "--offline", handle.name]), 2)
        os.unlink(handle.name)


class ScanParagraphs(unittest.TestCase):
    def test_lists_references_but_not_citation_years(self):
        text = ("In *A v B* [2015] UKSC 11 at [87] and [89]–[91]; see [207(vii)].\n"
                "No references here, only [2019] EWHC 936 (QB).\n"
                "Montgomery para 87 and paras 81-83.")
        got = cp.scan_paragraph_refs(text)
        self.assertEqual([(g["line"], g["refs"]) for g in got],
                         [(1, ["[87]", "[89]–[91]", "[207(vii)]"]), (3, ["para 87", "paras 81-83"])])


class Courts(unittest.TestCase):
    def test_court_words_and_abbreviations(self):
        self.assertEqual(cp.court_check("the Court of Appeal", "EWCA"), "match")
        self.assertEqual(cp.court_check("CA", "EWCA"), "match")
        self.assertEqual(cp.court_check("High Court (King's Bench Division)", "EWHC"), "match")
        self.assertEqual(cp.court_check("Supreme Court", "EWHC"), "conflict")
        self.assertEqual(cp.court_check("CA", "UKSC"), "conflict")
        self.assertEqual(cp.court_check("the tribunal below", "EWHC"), "unknown")
        self.assertEqual(cp.court_check("EAT", "EAT"), "match")


class Pinpoints(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(cp.parse_paras([87, "108-109", "[66]", "[312]-[314]", "[207(vii)]",
                                         "[303(ii)]-[303(iii)]", "para 20"]),
                         [20, 66, 87, 108, 109, 207, 303, 312, 313, 314])


class Report(unittest.TestCase):
    def test_problems_first_and_summary(self):
        rows = [
            {"citation": "A", "name": "", "verdict": cp.VERIFIED, "detail": "", "link": "", "pinpoints": []},
            {"citation": "B", "name": "x|y", "verdict": cp.NOT_FOUND, "detail": "", "link": "", "pinpoints": []},
            {"citation": "C", "name": "", "verdict": cp.MISMATCH, "detail": "", "link": "", "pinpoints": []},
        ]
        out = cp.report(rows).split("\n")
        self.assertTrue(out[2].startswith("| C ") and out[3].startswith("| B ") and out[4].startswith("| A "))
        self.assertIn("x\\|y", out[3])
        self.assertIn("3 citations: 1 verified, 1 mismatch, 1 not found.", out)
        self.assertIn(cp.ATTRIBUTION, out[-1])


if __name__ == "__main__":
    unittest.main()
