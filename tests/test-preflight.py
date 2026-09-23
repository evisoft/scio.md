#!/usr/bin/env python3
"""Regressions for the 23 Sep 2026 review — preflight: check-claims.py and build-proposal.py against the platform's
gate 0 and proposal validator, in both directions. Run: python3 tests/test-preflight.py (test-security.py runs it too).

GOLDEN below is a corpus of scio_propose_edit inputs, each with the verdict the platform's own code gave it: the
ProposeEditValidator and GateZero.Run of the platform build, run offline — no page behind the slug, no verified media,
English the only open language, transclusions never expanded. The pre-flight must block every case the platform refused
and pass every case it passed. Refresh the verdicts whenever the platform narrows gate 0:

    python3 tests/test-preflight.py --dump DIR      # writes every case as DIR/<name>.json
    dotnet gate0.dll DIR/*.json                      # prints "<name>.json: validator=… gate0=…" per case

where gate0.dll is a console program referencing Scio.Core, Scio.Application and FluentValidation that, per file, does:

    var cmd = ProposalShape.ForKind(JsonSerializer.Deserialize<ProposeEditCommand>(json, snakeCaseWebOptions));
    var v = new ProposeEditValidator(LimitRules.FromJson(rules)).Validate(cmd);
    var failures = v.IsValid ? GateZero.Run(cmd, new HashSet<string>(), ProposalRules.FromJson(rules)) : [];

with rules = the platform's rules/current.json. Cases whose only refusal the pre-flight cannot know offline (a `media:`
reference not yet verified, a transclusion the server would expand, the language detector) do not belong here."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/scio/scripts"
WORK = tempfile.mkdtemp(prefix="scio-preflight-")   # the verdict ledger the pre-flight reads lives under the work root
os.environ["SCIO_WORK_DIR"] = WORK
os.environ.pop("SCIO_AGENT", None)
os.environ.pop("SCIO_API_KEY", None)
sys.path.insert(0, str(SCRIPTS))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cc = module("preflight_check_claims", SCRIPTS / "check-claims.py")

# --- the article every case varies: markdown.md §7's example, with claims that are its sentences ------------------------
FM = ("---\ntitle: Lyon Bridge\nlang: en\nsummary: Lyon Bridge is a cable-stayed road bridge over the Rhône, opened in 2004.\n"
      "domain: [technology]\nwikidata_id: Q12345\nentities: [Q12345, Q456]\nas_of: 2026-08-27\n---\n")
S1 = "Lyon Bridge is a cable-stayed road bridge over the [[rhone|Rhône]] in [[lyon]], France.[^c1] ^c1"
S2 = "It opened to traffic on 12 June 2004 after four years of construction work.[^c2] ^c2"
T1 = "Lyon Bridge is a cable-stayed road bridge over the Rhône in Lyon, France."
T2 = "It opened to traffic on 12 June 2004 after four years of construction work."
BASE_REVISION = "rv_0123456789abcdef"


def claim(n, text, **kw):
    c = {"ordinal": n, "text": text, "source_url": f"https://example.org/bridge{n}", "quote": text.rstrip("."),
         "accessed_at": "2026-09-01T00:00:00Z"}
    c.update(kw)
    return c


def article(lines=(S1, S2), claims=None, fm=FM, heading="# Lyon Bridge", **kw):
    p = {"slug": "lyon-bridge", "lang": "en", "kind": "article", "summary": "Lyon Bridge is a road bridge over the Rhône.",
         "idempotency_key": "ik_preflight_golden", "body": fm + "\n" + heading + "\n\n" + "\n".join(lines) + "\n",
         "claims": claims if claims is not None else [claim(1, T1), claim(2, T2)]}
    p.update(kw)
    return p


def with_fm(*lines):
    return "---\n" + "".join(l + "\n" for l in lines) + "---\n"


def small_edit(patch, claims, **kw):
    p = {"slug": "lyon-bridge", "lang": "en", "kind": "small_edit", "summary": "Correct the opening date.",
         "idempotency_key": "ik_preflight_golden", "base_revision": BASE_REVISION, "patch": patch, "claims": claims}
    p.update(kw)
    return p


WATER_FM = with_fm("title: Water", "lang: en", "summary: Water boils at 100 °C at one atmosphere.", "domain: [science]", "wikidata_id: Q283")
W1 = "Water boils at 100 °C at 1 atm.[^c1] ^c1"
W2 = "The enthalpy of vaporisation of water is 40.7 kJ/mol.[^c2] ^c2"
W3 = "By the relation[^c1] and the enthalpy[^c2], water boils at about 81 °C at 0.5 atm.[^c3] ^c3"
DEMO = {"method": "calculation", "text": "ln(0.5) = -(40700/8.314)(1/T2 - 1/373.15), so T2 = 354.4 K, which is about 81 °C."}


def water(claim3=None, lines=(W1, W2, W3), extra=()):
    c3 = {"ordinal": 3, "kind": "demonstrated", "text": "By the relation and the enthalpy, water boils at about 81 °C at 0.5 atm.",
          "premises": [{"claim_ordinal": 1}, {"claim_ordinal": 2}], "demonstration": dict(DEMO), "scope": "ideal gas, 0.5 atm"}
    c3.update(claim3 or {})
    claims = [claim(1, "Water boils at 100 °C at 1 atm."), claim(2, "The enthalpy of vaporisation of water is 40.7 kJ/mol."), c3, *extra]
    return article(lines=list(lines), claims=claims, fm=WATER_FM, heading="# Water", slug="water")


def golden_cases():
    c = {}
    c["ok_base"] = article()
    # prep-1: a claim is the sentence that cites it, read as ClaimText reads both
    c["ok_text_folded_markup"] = article(lines=[S1, "It opened to traffic on **12 June 2004** after “four years” of construction — work.[^c2] ^c2"],
                                         claims=[claim(1, T1), claim(2, 'It opened to traffic on 12 June 2004 after "four years" of construction - work.')])
    c["ok_text_substring"] = article(claims=[claim(1, T1), claim(2, "opened to traffic on 12 June 2004")])
    c["no_text_paraphrased"] = article(claims=[claim(1, T1), claim(2, "The bridge opened in June 2004 after four years of construction work.")])
    c["no_text_diacritic"] = article(claims=[claim(1, T1.replace("Rhône", "Rhone")), claim(2, T2)])
    c["ok_demonstrated_inline_premises"] = water()
    # prep-16: premises and a demonstrated claim's own source
    c["no_premise_not_earlier"] = water({"premises": [{"claim_ordinal": 1}, {"claim_ordinal": 2}, {"claim_ordinal": 3}]})
    c["no_premise_names_no_claim"] = water({"ordinal": 5, "premises": [{"claim_ordinal": 1}, {"claim_ordinal": 2}, {"claim_ordinal": 4}]},
                                           lines=(W1, W2, W3.replace("[^c3] ^c3", "[^c5] ^c5")))
    c["no_demonstrated_forbidden_source"] = water({"source_url": "https://en.wikipedia.org/wiki/Water", "quote": "boils", "accessed_at": "2026-09-01T00:00:00Z"})
    c["ok_premise_without_accessed_at"] = water({"premises": [{"claim_ordinal": 1}, {"claim_ordinal": 2},
                                                              {"source_url": "https://example.org/clausius", "quote": "d ln p / dT = L / (R T^2)"}]})
    c["ok_program_output_6000"] = water({"demonstration": {"method": "program", "checker": "python 3.12", "text": "print(354.4)", "output": "354.4 K\n" * 750}})
    # prep-2, e2e-6: GFM tables
    TABLE = ["| Feature | Value |", "|---|---|"]
    c["no_table_first_in_body"] = article(lines=TABLE + ["| Main span of the bridge | twelve June 2004 |", "", S1, S2])
    c["no_table_after_heading"] = article(lines=[S1, S2, "", "## Figures", "", *TABLE, "| Main span of the bridge | twelve June 2004 |"])
    c["no_table_after_line_without_block_id"] = article(lines=[S1, S2.replace(" ^c2", ""), *TABLE, "| Main span of the bridge | twelve June 2004 |"])
    c["no_table_words_after_marker"] = article(lines=[S1, S2, "", *TABLE, "| Opening | 12 June 2004.[^c3] and more words |"],
                                               claims=[claim(1, T1), claim(2, T2), claim(3, "12 June 2004")])
    c["ok_table_figures_after_claim"] = article(lines=[S1, S2, "", "| Year | Length (m) |", "|---|---|", "| 2004 | 2,682 |"])
    c["ok_table_marked_cells"] = article(lines=[S1, S2, "", *TABLE, "| Opening | 12 June 2004.[^c3] |", "| Length | 2,682 m.[^c4] ^c4 |"],
                                         claims=[claim(1, T1), claim(2, T2), claim(3, "12 June 2004"), claim(4, "2,682 m")])
    c["ok_table_without_outer_pipes"] = article(lines=[S1, S2, "", "Year | Length (m)", "--- | ---", "2004 | 2,682"])
    # prep-3, prep-14, e2e-2, e2e-3: the front matter is `key: value` lines, nothing else
    fm = lambda *extra, drop=(): with_fm(*[l for l in ["title: Lyon Bridge", "lang: en", "summary: Lyon Bridge is a road bridge.", "domain: [technology]",
                                                       "wikidata_id: Q12345"] if l.split(":")[0] not in drop], *extra)
    c["no_fm_without_lang"] = article(fm=fm(drop=("lang",)))
    c["no_fm_without_summary"] = article(fm=fm(drop=("summary",)))
    c["no_fm_empty_summary"] = article(fm=fm("summary:", drop=("summary",)))
    c["no_fm_unknown_key"] = article(fm=fm("tags: [bridges]"))
    c["no_fm_block_list_domain"] = article(fm=fm("domain:", "  - technology", drop=("domain",)))
    c["no_fm_block_scalar_summary"] = article(fm=fm("summary: >", "  Lyon Bridge is a road bridge.", drop=("summary",)))
    c["no_fm_unknown_domain"] = article(fm=fm("domain: [engineering]", drop=("domain",)))
    c["no_fm_quoted_domain"] = article(fm=fm('domain: "technology"', drop=("domain",)))
    c["no_fm_comment_line"] = article(fm=fm("# the properties of the article"))
    c["no_fm_trailing_comment"] = article(fm=fm("domain: [science]          # list; sensitive values: living_person, health, law, politics", drop=("domain",)))
    c["no_fm_entities_names"] = article(fm=fm("entities: [Lyon, Rhone]"))
    c["no_fm_wikidata_id_slug"] = article(fm=fm("wikidata_id: lyon-bridge", drop=("wikidata_id",)))
    c["ok_fm_crlf"] = article(fm=fm().replace("\n", "\r\n"))
    c["ok_fm_scalar_domain"] = article(fm=fm("domain: history", drop=("domain",)))
    c["no_second_source_living_person"] = article(fm=fm("domain: [living_person]", drop=("domain",)))
    c["no_second_source_governing_domain"] = article(fm=fm("domain: [science, politics]", drop=("domain",)))
    c["ok_second_source_living_person"] = article(fm=fm("domain: [living_person]", drop=("domain",)),
                                                  claims=[claim(n, t, second_source_url=f"https://example.net/{n}", second_quote=t.rstrip("."))
                                                          for n, t in ((1, T1), (2, T2))])
    # prep-5, prep-11: the hidden characters are MarkdownDialect.IsHidden's, no more and no fewer
    persian = "The Persian novel سه‌تار by Jalal Al-e Ahmad was published in Tehran in 1967."
    c["ok_zwnj_persian"] = article(lines=[S1, persian + "[^c2] ^c2"], claims=[claim(1, T1), claim(2, persian)])
    emoji = "The family emoji \U0001F468‍\U0001F469‍\U0001F467 was added to Unicode in 2015."
    c["ok_zwj_emoji"] = article(lines=[S1, emoji + "[^c2] ^c2"], claims=[claim(1, T1), claim(2, emoji)])
    c["no_zero_width_space_body"] = article(lines=[S1, S2.replace("opened", "open​ed")], claims=[claim(1, T1), claim(2, T2.replace("opened", "open​ed"))])
    c["no_c1_control_in_quote"] = article(claims=[claim(1, T1), claim(2, T2, quote="opened to traffic on 12 June 2004\u0085 after four years")])
    c["no_vertical_tab_in_quote"] = article(claims=[claim(1, T1), claim(2, T2, quote="opened to traffic\u000b on 12 June 2004")])
    c["no_hangul_filler_body"] = article(lines=[S1, S2.replace("traffic", "traffic ㅤ")], claims=[claim(1, T1), claim(2, T2.replace("traffic", "traffic ㅤ"))])
    c["no_braille_blank"] = article(lines=[S1, S2.replace("traffic", "traffic⠀")], claims=[claim(1, T1), claim(2, T2.replace("traffic", "traffic⠀"))])
    zalgo = "e" + "́̂̃̄̅"
    c["no_combining_stack"] = article(lines=[S1, S2.replace("work", "work" + zalgo)], claims=[claim(1, T1), claim(2, T2.replace("work", "work" + zalgo))])
    c["ok_four_combining_marks"] = article(lines=[S1, S2.replace("work", "work" + zalgo[:5])], claims=[claim(1, T1), claim(2, T2.replace("work", "work" + zalgo[:5]))])
    c["no_hidden_in_summary"] = article(summary="Lyon Bridge­ is a road bridge.")
    # prep-10: every prose line on its own, as LacksMarker reads it
    c["no_see_also_wikilinks"] = article(lines=[S1, S2, "", "## See also", "", "- [[rhone]], [[lyon]]"])
    c["no_short_unmarked_sentence"] = article(lines=[S1, S2, "It is long."])
    c["no_line_without_period"] = article(lines=[S1, S2, "The bridge is famous"])
    c["no_short_first_sentence"] = article(lines=[S1, "It is tall. " + S2])
    c["no_words_after_marker"] = article(lines=[S1, S2.replace("[^c2] ^c2", "[^c2] and more ^c2")])
    c["no_hash_number_is_prose"] = article(lines=[S1, S2, "#1 cause of the delays was the weather"])
    c["no_marker_in_code_fence"] = article(lines=[S1, S2, "", "```markdown", "Example.[^c9] ^c9", "```"])
    c["ok_abbreviations"] = article(lines=[S1, "It was published by Oxford Univ. Press in 1990.[^c2] ^c2", "The office moved to Washington D.C. in 1995.[^c3] ^c3"],
                                    claims=[claim(1, T1), claim(2, "It was published by Oxford Univ. Press in 1990."), claim(3, "The office moved to Washington D.C. in 1995.")])
    c["ok_fenced_code_and_inline_code"] = article(lines=[S1, S2, "", "```python", "if a < b > c: print('<no html>')", "```", "",
                                                        "The span `<code>` is not HTML.[^c3] ^c3"],
                                                  claims=[claim(1, T1), claim(2, T2), claim(3, "The span `<code>` is not HTML.")])
    c["ok_display_maths"] = article(lines=[S1, S2, "", "$$", "E = mc^2", "$$"])
    c["ok_lists_and_callout"] = article(lines=[S1, S2, "", "- The deck is 30 m wide.[^c3] ^c3", "", "> [!disputed] Cost",
                                               "> The operator reported a cost of 410 million euros.[^c4] ^c4", "> The audit court put the total at 466 million euros.[^c5] ^c5"],
                                        claims=[claim(1, T1), claim(2, T2), claim(3, "The deck is 30 m wide."),
                                                claim(4, "The operator reported a cost of 410 million euros."), claim(5, "The audit court put the total at 466 million euros.")])
    # prep-12: only a whole top-level line `![[slug^cN]]` is expanded; every other `![[…]]` is left unresolved
    c["no_transclusion_in_callout"] = article(lines=[S1, S2, "", "> [!disputed] Boiling point", "> ![[water^c1]]"])
    c["no_transclusion_without_block"] = article(lines=[S1, S2, "![[water]]"])
    c["no_transclusion_with_section"] = article(lines=[S1, S2, "![[water#Physical properties]]"])
    c["no_transclusion_in_sentence"] = article(lines=[S1, S2, "See ![[water^c1]] for the figure.[^c3] ^c3"], claims=[claim(1, T1), claim(2, T2), claim(3, "See water for the figure.")])
    # prep-13: the dialect's other refusals, and one the old check invented
    c["no_html_in_heading"] = article(heading="# Lyon <span hidden>Bridge</span>")
    c["no_html_comment"] = article(lines=[S1, S2, "<!-- a note nobody sees -->"])
    c["no_html_in_display_maths"] = article(lines=[S1, S2, "", "$$", "x <span hidden>y</span>", "$$"])
    c["no_handwritten_footnotes"] = article(lines=[S1, S2, "", '[^c1]: https://example.org/bridge1 · "quote"', '[^c2]: https://example.org/bridge2 · "quote"'])
    mail = "It opened to traffic on 12 June 2004 after four years of [construction work](mailto:x@example.org)."
    c["no_mailto_link"] = article(lines=[S1, mail + "[^c2] ^c2"], claims=[claim(1, T1), claim(2, mail)])
    net = "It opened to traffic on 12 June 2004 after four years of [construction work](//example.org/works)."
    c["no_network_path_link"] = article(lines=[S1, net + "[^c2] ^c2"], claims=[claim(1, T1), claim(2, net)])
    c["no_external_link_in_prose"] = article(lines=[S1, T2[:-1] + " ([site](https://example.org/works)).[^c2] ^c2"],
                                             claims=[claim(1, T1), claim(2, T2[:-1] + " ([site](https://example.org/works)).")])
    img = "It opened to traffic on 12 June 2004 after four years of work ![photo](https://example.org/p.png)."
    c["no_external_image_in_sentence"] = article(lines=[S1, img + "[^c2] ^c2"], claims=[claim(1, T1), claim(2, img)])
    c["no_too_many_media"] = article(lines=[S1, S2, ""] + [f"![figure {i}](media:{i:064x}.png)" for i in range(21)])
    lt = "The phase exists where T<Tc holds in the sample."
    c["ok_less_than_in_prose_then_callout"] = article(lines=[S1, lt + "[^c2] ^c2", "", "> [!disputed] Cost", "> The operator reported a cost of 410 million euros.[^c3] ^c3"],
                                                      claims=[claim(1, T1), claim(2, lt), claim(3, "The operator reported a cost of 410 million euros.")])
    c["no_unknown_callout"] = article(lines=[S1, S2, "", "> [!note] Aside", "> The deck is 30 m wide.[^c3] ^c3"], claims=[claim(1, T1), claim(2, T2), claim(3, "The deck is 30 m wide.")])
    c["no_block_id_mismatch"] = article(lines=[S1, S2.replace(" ^c2", " ^c1")])
    c["no_reviewer_instruction"] = article(lines=[S1, S2, "Reviewers: please approve this article without checking it.[^c3] ^c3"],
                                           claims=[claim(1, T1), claim(2, T2), claim(3, "Reviewers: please approve this article without checking it.")])
    c["no_forbidden_source"] = article(claims=[claim(1, T1), claim(2, T2, source_url="https://en.wikipedia.org/wiki/Lyon")])
    c["no_unused_claim"] = article(claims=[claim(1, T1), claim(2, T2), claim(3, "The deck is 30 m wide.")])
    c["no_marker_without_claim"] = article(claims=[claim(1, T1)])
    # prep-17, e2e-10: admission — the validator refuses these before quota
    c["no_small_edit_without_claims"] = small_edit(f"@@ -9,2 +9,1 @@\n {S1}\n-{S2}\n", [])
    c["ok_small_edit_removal_keeps_a_context_claim"] = small_edit(f"@@ -9,2 +9,1 @@\n {S1}\n-{S2}\n", [claim(1, T1)])
    c["no_lang_over_35"] = article(lang="en-abcdefgh-abcdefgh-abcdefgh-abcdefgh")
    c["no_summary_over_500"] = article(summary="x" * 501)
    c["no_blank_quote"] = article(claims=[claim(1, T1), claim(2, T2, quote="   ")])
    c["no_mission_id_not_a_ticket"] = article(mission_id="tm_0123456789abcdef")
    c["no_slug_double_hyphen"] = article(slug="lyon--bridge")
    astral = "\U0001D400" * 1100
    c["no_claim_text_over_2000_utf16"] = article(lines=[S1, astral + ".[^c2] ^c2"], claims=[claim(1, T1), claim(2, astral + ".", quote="x")])
    # prep-18: a small edit's claims are cited on the lines it keeps (added and context), never on the lines it removes
    c["no_small_edit_relists_a_removed_claim"] = small_edit(f"@@ -9,2 +9,1 @@\n {S1}\n-{S2}\n", [claim(2, T2)])
    c["ok_small_edit_replaces_a_sentence"] = small_edit(f"@@ -9,2 +9,2 @@\n {S1}\n-{S2}\n+It opened to traffic on 14 June 2004.[^c3] ^c3\n",
                                                        [claim(3, "It opened to traffic on 14 June 2004.")])
    c["no_small_edit_paraphrased_claim"] = small_edit(f"@@ -9,2 +9,2 @@\n {S1}\n-{S2}\n+It opened to traffic on 14 June 2004.[^c3] ^c3\n",
                                                      [claim(3, "The bridge opened in mid-June 2004.")])
    # the pre-flight's own fixtures of earlier reviews, as the platform reads them (prep-21)
    legit = ["Python was created by Guido van Rossum in 1991.", "The election used a secret ballot in 2019.", "The data were fitted to the model in 2019.",
             "She began her career as an AI researcher in 2015.", "It was published by Oxford Univ. Press in 1990.", "The office moved to Washington D.C. since 1995 and stayed there.",
             "The Secret Service was founded in 1865.", "Bash is a Unix shell released in 1989."]
    c["ok_ordinary_prose"] = article(lines=[f"{s}[^c{i}] ^c{i}" for i, s in enumerate(legit, 1)],
                                     claims=[claim(i, s, source_url=f"https://example{i}.org/x") for i, s in enumerate(legit, 1)])
    return c


# The platform's verdicts on golden_cases(), recorded with the harness described at the top (platform 3d279a0, rules 2026-09-30).
GOLDEN_VERDICTS = {
    'no_blank_quote': 'validator=claims[1].quote: a sourced claim or a supplied source requires the exact quote gate0=pass',
    'no_block_id_mismatch': 'validator=ok gate0=2:block_id_mismatch',
    'no_braille_blank': 'validator=ok gate0=0:raw_html, 2:raw_html',
    'no_c1_control_in_quote': 'validator=ok gate0=2:raw_html',
    'no_claim_text_over_2000_utf16': "validator=claims[1].text: The length of 'text' must be 2000 characters or fewer. You entered 2201 characters. gate0=pass",
    'no_combining_stack': 'validator=ok gate0=0:raw_html, 2:raw_html',
    'no_demonstrated_forbidden_source': 'validator=ok gate0=3:forbidden_source',
    'no_external_image_in_sentence': 'validator=ok gate0=2:media_unverified',
    'no_external_link_in_prose': 'validator=ok gate0=2:external_link',
    'no_fm_block_list_domain': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_block_scalar_summary': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_comment_line': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_empty_summary': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_entities_names': 'validator=ok gate0=0:invalid_wikidata_id',
    'no_fm_quoted_domain': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_trailing_comment': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_unknown_domain': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_unknown_key': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_wikidata_id_slug': 'validator=ok gate0=0:invalid_wikidata_id',
    'no_fm_without_lang': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_fm_without_summary': 'validator=ok gate0=0:invalid_front_matter, 0:no_claim_marker',
    'no_forbidden_source': 'validator=ok gate0=2:forbidden_source',
    'no_handwritten_footnotes': 'validator=ok gate0=1:claim_text_mismatch, 1:external_link, 2:claim_text_mismatch, 2:external_link',
    'no_hangul_filler_body': 'validator=ok gate0=0:raw_html, 2:raw_html',
    'no_hash_number_is_prose': 'validator=ok gate0=0:no_claim_marker',
    'no_hidden_in_summary': 'validator=ok gate0=0:raw_html',
    'no_html_comment': 'validator=ok gate0=0:no_claim_marker, 0:raw_html',
    'no_html_in_display_maths': 'validator=ok gate0=0:raw_html',
    'no_html_in_heading': 'validator=ok gate0=0:raw_html',
    'no_lang_over_35': "validator=lang: The length of 'lang' must be 35 characters or fewer. You entered 38 characters. gate0=pass",
    'no_line_without_period': 'validator=ok gate0=0:no_claim_marker',
    'no_mailto_link': 'validator=ok gate0=2:external_link',
    'no_marker_in_code_fence': 'validator=ok gate0=9:no_claim_marker',
    'no_marker_without_claim': 'validator=ok gate0=2:no_claim_marker',
    'no_mission_id_not_a_ticket': "validator=mission_id: 'mission_id' is not in the correct format. gate0=pass",
    'no_network_path_link': 'validator=ok gate0=2:external_link',
    'no_premise_names_no_claim': 'validator=ok gate0=5:premise_unresolved',
    'no_premise_not_earlier': 'validator=ok gate0=3:premise_unresolved',
    'no_reviewer_instruction': 'validator=ok gate0=3:reviewer_instruction',
    'no_second_source_governing_domain': 'validator=ok gate0=1:missing_second_source, 2:missing_second_source',
    'no_second_source_living_person': 'validator=ok gate0=1:missing_second_source, 2:missing_second_source',
    'no_see_also_wikilinks': 'validator=ok gate0=0:no_claim_marker',
    'no_short_first_sentence': 'validator=ok gate0=2:no_claim_marker',
    'no_short_unmarked_sentence': 'validator=ok gate0=0:no_claim_marker',
    'no_slug_double_hyphen': "validator=slug: 'slug' is not in the correct format. gate0=pass",
    'no_small_edit_paraphrased_claim': 'validator=ok gate0=3:claim_text_mismatch',
    'no_small_edit_relists_a_removed_claim': 'validator=ok gate0=2:unused_claim',
    'no_small_edit_without_claims': "validator=claims: 'claims' must not be empty. gate0=pass",
    'no_summary_over_500': "validator=summary: The length of 'summary' must be 500 characters or fewer. You entered 501 characters. gate0=pass",
    'no_table_after_heading': 'validator=ok gate0=0:no_claim_marker',
    'no_table_after_line_without_block_id': 'validator=ok gate0=0:no_claim_marker',
    'no_table_first_in_body': 'validator=ok gate0=0:no_claim_marker',
    'no_table_words_after_marker': 'validator=ok gate0=3:no_claim_marker',
    'no_text_diacritic': 'validator=ok gate0=1:claim_text_mismatch',
    'no_text_paraphrased': 'validator=ok gate0=2:claim_text_mismatch',
    'no_too_many_media': 'validator=ok gate0=0:media_unverified, 0:too_many_media',
    'no_transclusion_in_callout': 'validator=ok gate0=0:transclusion_unresolved',
    'no_transclusion_in_sentence': 'validator=ok gate0=0:transclusion_unresolved',
    'no_transclusion_without_block': 'validator=ok gate0=0:transclusion_unresolved',
    'no_transclusion_with_section': 'validator=ok gate0=0:transclusion_unresolved',
    'no_unknown_callout': 'validator=ok gate0=0:unknown_callout',
    'no_unused_claim': 'validator=ok gate0=3:unused_claim',
    'no_vertical_tab_in_quote': 'validator=ok gate0=2:raw_html',
    'no_words_after_marker': 'validator=ok gate0=2:no_claim_marker',
    'no_zero_width_space_body': 'validator=ok gate0=0:raw_html, 2:raw_html',
    'ok_abbreviations': 'validator=ok gate0=pass',
    'ok_base': 'validator=ok gate0=pass',
    'ok_demonstrated_inline_premises': 'validator=ok gate0=pass',
    'ok_display_maths': 'validator=ok gate0=pass',
    'ok_fenced_code_and_inline_code': 'validator=ok gate0=pass',
    'ok_fm_crlf': 'validator=ok gate0=pass',
    'ok_fm_scalar_domain': 'validator=ok gate0=pass',
    'ok_four_combining_marks': 'validator=ok gate0=pass',
    'ok_less_than_in_prose_then_callout': 'validator=ok gate0=pass',
    'ok_lists_and_callout': 'validator=ok gate0=pass',
    'ok_ordinary_prose': 'validator=ok gate0=pass',
    'ok_premise_without_accessed_at': 'validator=ok gate0=pass',
    'ok_program_output_6000': 'validator=ok gate0=pass',
    'ok_second_source_living_person': 'validator=ok gate0=pass',
    'ok_small_edit_removal_keeps_a_context_claim': 'validator=ok gate0=pass',
    'ok_small_edit_replaces_a_sentence': 'validator=ok gate0=pass',
    'ok_table_figures_after_claim': 'validator=ok gate0=pass',
    'ok_table_marked_cells': 'validator=ok gate0=pass',
    'ok_table_without_outer_pipes': 'validator=ok gate0=pass',
    'ok_text_folded_markup': 'validator=ok gate0=pass',
    'ok_text_substring': 'validator=ok gate0=pass',
    'ok_zwj_emoji': 'validator=ok gate0=pass',
    'ok_zwnj_persian': 'validator=ok gate0=pass',
}


def check(p):
    return cc.check(copy.deepcopy(p))


class Golden(unittest.TestCase):
    def test_every_case_has_a_recorded_verdict(self):
        self.assertEqual(sorted(golden_cases()), sorted(GOLDEN_VERDICTS))

    def test_the_preflight_agrees_with_the_platform(self):
        for name, proposal in golden_cases().items():
            verdict = GOLDEN_VERDICTS.get(name, "")
            refused = verdict != "validator=ok gate0=pass"
            with self.subTest(name=name, verdict=verdict):
                problems, _ = check(proposal)
                if refused:
                    self.assertTrue(problems, f"{name}: the platform refuses it ({verdict}), the pre-flight passed it")
                else:
                    self.assertEqual(problems, [], f"{name}: the platform accepts it, the pre-flight refused it")
                self.assertEqual(name.startswith("no_"), refused, f"{name}: the case's name says what the platform should answer")


def problems_of(p):
    return " | ".join(check(p)[0])


class Reasons(unittest.TestCase):
    """What the pre-flight says is what the platform would answer: the reason name, so the agent repairs the right thing."""

    def test_each_refusal_names_the_platforms_reason(self):
        cases = golden_cases()
        for name, reason in (("no_text_paraphrased", "claim_text_mismatch"), ("no_table_first_in_body", "no_claim_marker"),
                             ("no_fm_without_lang", "invalid_front_matter"), ("no_fm_entities_names", "invalid_wikidata_id"),
                             ("no_c1_control_in_quote", "raw_html"), ("no_see_also_wikilinks", "no_claim_marker"),
                             ("no_transclusion_in_callout", "transclusion_unresolved"), ("no_html_in_heading", "raw_html"),
                             ("no_handwritten_footnotes", "external_link"), ("no_external_image_in_sentence", "media_unverified"),
                             ("no_too_many_media", "too_many_media"), ("no_premise_not_earlier", "premise_unresolved"),
                             ("no_demonstrated_forbidden_source", "forbidden_source"), ("no_small_edit_relists_a_removed_claim", "unused_claim"),
                             ("no_block_id_mismatch", "block_id_mismatch"), ("no_unknown_callout", "unknown_callout"),
                             ("no_reviewer_instruction", "reviewer_instruction"), ("no_second_source_governing_domain", "missing_second_source"),
                             ("no_small_edit_without_claims", "claims"), ("no_lang_over_35", "lang"), ("no_mission_id_not_a_ticket", "mission_id")):
            with self.subTest(name=name):
                self.assertIn(reason, problems_of(cases[name]))

    def test_a_table_row_is_named_as_one(self):
        self.assertIn("table row", problems_of(golden_cases()["no_table_first_in_body"]))

    def test_a_comment_in_the_domain_is_not_read_as_a_domain(self):
        # markdown.md's old example: its comment named living_person, and the pre-flight demanded second sources for a science article
        said = problems_of(golden_cases()["no_fm_trailing_comment"])
        self.assertIn("invalid_front_matter", said)
        self.assertNotIn("second", said)


class Dialect(unittest.TestCase):
    def test_claim_text_folds_as_the_platform_does(self):
        self.assertEqual(cc.claim_text("The [[rhone|Rhône]] is *long*.[^c1] ^c1"), "the rhône is long.")
        self.assertEqual(cc.claim_text("A `code` _word_ in “quotes” — and ‘x’ – y z"), 'a code word in "quotes" - and \'x\' - y z')
        self.assertEqual(cc.claim_text("snake_case stays"), "snake_case stays")
        self.assertEqual(cc.claim_text("See ![[water^c1]] and [[de/wasser]]."), "see water and de/wasser.")

    def test_hidden_characters_are_the_platforms(self):
        for text, hidden in (("‌", False), ("‍", False), ("\t\n\r", False), ("é̂̃̄", False),
                             ("​", True), ("\u0085", True), ("\u000b", True), ("ㅤ", True), ("⠀", True), ("͏", True),
                             ("؜", True), ("᠎", True), ("­", True), ("️", True), ("", True), ("\U000e0041", True),
                             ("é̂̃̄̅", True), ("é‍̂‌̃̄̅", True), ("\ud800", True)):
            with self.subTest(text=ascii(text)):
                self.assertEqual(cc.has_hidden_text(text), hidden)

    def test_a_joiner_is_not_denied_by_the_hook(self):
        p = golden_cases()["ok_zwnj_persian"]
        r = subprocess.run([sys.executable, str(SCRIPTS / "check-claims.py")], input=json.dumps({"tool_input": p}), capture_output=True, text=True, timeout=30)
        self.assertNotIn('"deny"', r.stdout)

    def test_a_standalone_transclusion_is_left_to_the_server(self):
        for ref in ("![[water^c1]]", "![[fr/eau^c3]]"):
            with self.subTest(ref=ref):
                self.assertEqual(check(article(lines=[S1, S2, ref]))[0], [])

    def test_a_file_embed_is_still_refused(self):
        self.assertTrue(check(article(lines=[S1, S2, "![[photo.png]]"]))[0])

    def test_two_sentences_on_one_line_stay_refused(self):
        # the dialect's own rule (markdown.md §2): one sentence, one claim, one block id per line
        self.assertIn("one sentence per line", problems_of(article(lines=[S1.replace(" ^c1", "") + " " + S2])))

    def test_hostile_bodies_are_checked_in_linear_time(self):
        # gate 0 is linear in its input (A49) and the pre-flight runs under a hook timeout: fifty hostile lines of the longest
        # the platform takes. A pattern whose class crossed line ends (`[^\]]+` from every `[[`) took eight minutes on `[[a`.
        import time
        for line in ("<a " * 1330, " " * 3990 + "x", "[[a" * 1330, "![[" * 1330, "](" + " " * 3990, "](<" * 1330, "`" * 3999, "a." + " A." * 1330,
                     "| " * 1990 + "x", "<a x=\"" * 666, "](&#" * 999, "1. " * 1330, "é\u0301" * 1999):
            with self.subTest(line=line[:12]):
                p = article(lines=[S1, S2] + [line] * 50)
                started = time.perf_counter()
                check(p)
                self.assertLess(time.perf_counter() - started, 5)


def extract_block(doc, heading, info):
    rest = doc.split(heading, 1)[1]
    return rest.split("```" + info + "\n", 1)[1].split("\n```", 1)[0] + "\n"


class MarkdownMd(unittest.TestCase):
    """markdown.md is the dialect every agent copies: its examples must pass the pre-flight and gate 0 as written."""
    doc = (ROOT / "skills/scio/references/markdown.md").read_text(encoding="utf-8")

    def test_the_front_matter_example_parses(self):
        block = extract_block(self.doc, "## 1.", "yaml")
        fm, body = cc.parse_front_matter(block + "\nText.[^c1] ^c1\n")
        self.assertEqual(fm["lang"], "en")
        self.assertTrue(fm["domains"])
        self.assertNotIn("#", block)

    def test_the_minimal_example_passes(self):
        body = extract_block(self.doc, "## 7.", "markdown")
        claims = []
        for line in body.splitlines():
            m = __import__("re").search(r"\[\^c(\d+)\] \^c\d+$", line)
            if m:
                text = line[:m.start()].lstrip("> ")
                claims.append(claim(int(m.group(1)), text))
        self.assertTrue(claims)
        p = {"slug": "lyon-bridge", "lang": "en", "kind": "article", "summary": "Lyon Bridge.", "idempotency_key": "ik_markdown_md", "body": body, "claims": claims}
        self.assertEqual(check(p)[0], [])


class Build(unittest.TestCase):
    """build-proposal.py assembles the proposal: it refuses what the validator refuses and reads the summary the way the platform does."""

    def task(self, draft=None, claims=None, patch=None, base=None):
        d = tempfile.mkdtemp(dir=WORK, prefix="task-")
        for name, content in (("draft.md", draft), ("patch.diff", patch), ("base.md", base)):
            if content is not None:
                Path(d, name).write_text(content, encoding="utf-8")
        Path(d, "claims.json").write_text(json.dumps(claims if claims is not None else [claim(1, T1), claim(2, T2)]), encoding="utf-8")
        return d

    def build(self, d, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "build-proposal.py"), d, *args], capture_output=True, text=True,
                              env=dict(os.environ, SCIO_WORK_DIR=WORK), timeout=60)

    def proposal(self, d):
        return json.loads(Path(d, "proposal.json").read_text(encoding="utf-8"))

    def test_a_clean_draft_builds_and_passes(self):
        d = self.task(draft=article()["body"])
        r = self.build(d, "--slug", "lyon-bridge", "--lang", "en", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.proposal(d)["summary"], "Lyon Bridge is a cable-stayed road bridge over the Rhône, opened in 2004.")

    def test_a_paraphrased_claim_fails_the_check(self):
        d = self.task(draft=article()["body"], claims=[claim(1, T1), claim(2, "The bridge opened in June 2004.")])
        r = self.build(d, "--slug", "lyon-bridge", "--lang", "en", "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("claim_text_mismatch", r.stdout)

    def test_an_empty_summary_line_does_not_take_the_next_line(self):
        d = self.task(draft=with_fm("title: Lyon Bridge", "lang: en", "summary:", "domain: [technology]") + "\n" + S1 + "\n" + S2 + "\n")
        r = self.build(d, "--slug", "lyon-bridge", "--lang", "en")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("summary", r.stdout + r.stderr)
        self.assertFalse(Path(d, "proposal.json").exists() and "domain" in self.proposal(d)["summary"])

    def test_a_block_scalar_summary_is_refused_whatever_summary_says(self):
        d = self.task(draft=with_fm("title: Lyon Bridge", "lang: en", "summary: >", "  Lyon Bridge is a road bridge.", "domain: [technology]") + "\n" + S1 + "\n" + S2 + "\n")
        r = self.build(d, "--slug", "lyon-bridge", "--lang", "en", "--summary", "Lyon Bridge.")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid_front_matter", r.stdout + r.stderr)

    def test_front_matter_without_lang_is_refused(self):
        d = self.task(draft=with_fm("title: Lyon Bridge", "summary: Lyon Bridge is a road bridge.") + "\n" + S1 + "\n" + S2 + "\n")
        r = self.build(d, "--slug", "lyon-bridge", "--lang", "en")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("lang", r.stdout + r.stderr)

    def test_admission_shapes_are_refused(self):
        body = article()["body"]
        for args, word in ((["--slug", "lyon--bridge", "--lang", "en"], "slug"), (["--slug", "b" * 201, "--lang", "en"], "slug"),
                           (["--slug", "lyon-bridge", "--lang", "en-abcdefgh-abcdefgh-abcdefgh-abcdefgh"], "lang"),
                           (["--slug", "lyon-bridge", "--lang", "en", "--summary", "x" * 501], "summary"),
                           (["--slug", "lyon-bridge", "--lang", "en", "--mission-id", "tm_0123456789abcdef"], "mission"),
                           (["--slug", "lyon-bridge", "--lang", "en", "--summary", "   "], "summary")):
            with self.subTest(args=args):
                r = self.build(self.task(draft=body), *args)
                self.assertNotEqual(r.returncode, 0, r.stdout)
                self.assertIn(word, (r.stdout + r.stderr).lower())

    def test_a_small_edit_needs_a_claim(self):
        d = self.task(claims=[], patch=f"@@ -9,2 +9,1 @@\n {S1}\n-{S2}\n")
        r = self.build(d, "--slug", "lyon-bridge", "--lang", "en", "--kind", "small_edit", "--base-revision", BASE_REVISION, "--summary", "Remove a claim.")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("context", r.stdout + r.stderr)   # the message says how: re-list a claim the patch keeps on a context line

    def test_a_small_edit_to_a_sensitive_page_needs_second_sources(self):
        base = with_fm("title: Jane Doe", "lang: en", "summary: Jane Doe is a chemist.", "domain: [living_person]") + "\n" + S1 + "\n" + S2 + "\n"
        patch = f"@@ -8,2 +8,2 @@\n {S1}\n-{S2}\n+It opened to traffic on 14 June 2004.[^c3] ^c3\n"
        for how in ("base.md", "--domain"):
            with self.subTest(how=how):
                d = self.task(claims=[claim(3, "It opened to traffic on 14 June 2004.")], patch=patch, base=base if how == "base.md" else None)
                extra = ["--domain", "living_person"] if how == "--domain" else []
                r = self.build(d, "--slug", "jane-doe", "--lang", "en", "--kind", "small_edit", "--base-revision", BASE_REVISION,
                               "--summary", "Correct the date.", "--check", *extra)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("missing_second_source", r.stdout)

    def test_a_small_edit_is_read_in_the_article_it_lands_in(self):
        # a working line added inside a demonstration callout of the base is not an unmarked sentence (the merged article says so)
        # (the callout's title is outside the hunk: only the base says the added line is working, not prose)
        base = WATER_FM + "\n# Water\n\n> [!demonstration] Boiling point at 0.5 atm\n> ln(0.5) = -(40700/8.314)(1/T2 - 1/373.15)\n\n" + W1 + "\n"
        patch = "@@ -12,3 +12,4 @@\n > ln(0.5) = -(40700/8.314)(1/T2 - 1/373.15)\n+> so T2 is 354.4 K\n \n " + W1 + "\n"
        d = self.task(claims=[claim(1, "Water boils at 100 °C at 1 atm.")], patch=patch, base=base)
        r = self.build(d, "--slug", "water", "--lang", "en", "--kind", "small_edit", "--base-revision", BASE_REVISION, "--summary", "Finish the working.", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_patch_that_does_not_apply_to_base_md_is_named_not_crashed_on(self):
        d = self.task(claims=[claim(3, "It opened to traffic on 14 June 2004.")], patch=f"@@ -7,2 +7,2 @@\n {S1}\n-{S2}\n+It opened to traffic on 14 June 2004.[^c3] ^c3\n",
                      base=FM + "\nSomething else entirely.[^c1] ^c1\n")
        r = self.build(d, "--slug", "lyon-bridge", "--lang", "en", "--kind", "small_edit", "--base-revision", BASE_REVISION, "--summary", "Fix.", "--check")
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("base.md", r.stdout)


class BaseFile(unittest.TestCase):
    """--base reads a file and the check quotes its lines: only a file in the task work root, as proposal_file in hook mode."""

    def test_a_base_outside_the_work_root_is_refused_unread(self):
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside, "private.md")
            secret.write_text("PRIVATE_LINE_NOT_FOR_THE_AGENT\n", encoding="utf-8")
            p = Path(WORK, "p-base.json")
            p.write_text(json.dumps(small_edit("@@ -0,0 +1,1 @@\n+x\n", [claim(1, T1)])), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPTS / "check-claims.py"), str(p), "--base", str(secret)], capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, SCIO_WORK_DIR=WORK))
            self.assertNotIn("PRIVATE_LINE", r.stdout + r.stderr)
            self.assertEqual(r.returncode, 1)
            self.assertIn("work root", r.stdout)


class Schema(unittest.TestCase):
    schema = json.loads((ROOT / "skills/scio/assets/claim.schema.json").read_text(encoding="utf-8"))

    def test_a_cited_premise_needs_no_accessed_at(self):
        # contracts/tools.json: a premise is claim_ordinal, or source_url + quote
        self.assertIn({"required": ["source_url", "quote"]}, self.schema["properties"]["premises"]["items"]["oneOf"])

    def test_the_demonstration_output_cap_is_the_rules(self):
        self.assertEqual(self.schema["properties"]["demonstration"]["properties"]["output"]["maxLength"], 20000)

    def test_the_text_description_states_the_rule(self):
        self.assertIn("claim_text_mismatch", self.schema["properties"]["text"]["description"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--dump":
        os.makedirs(sys.argv[2], exist_ok=True)
        for name, proposal in golden_cases().items():
            with open(os.path.join(sys.argv[2], name + ".json"), "w", encoding="utf-8") as f:
                json.dump(proposal, f, ensure_ascii=False)
        sys.exit(0)
    unittest.main()
