# Writing standards

The constitution (rules.md, Part III) says what a good article *is*; this file is how to write one. The test for every sentence: could a reviewer, holding only the quote, confirm it in under a minute?

## Sentences

- **One claim per sentence.** Long sentences hide unsourced sub-claims. A claim's `text` is its sentence exactly as written, links and emphasis included ([markdown.md](markdown.md) §2). "Founded in 1998 in Lyon by two engineers, the company grew to 4,000 staff by 2020" is four claims; write them as sentences a quote can each support, or as one sentence only if one quote supports all four.
- **The sentence says what the quote says — no more.** Source: "roughly four in ten respondents" → write "about 40 % of respondents", not "40 %" and not "most". Source: "the 2019 audit" → write "in 2019", not "recently".
- **Concrete over abstract.** Numbers with units and dates; names with roles; places with countries; organisations with what they are on first mention.
- **Date what changes.** "As of March 2026 the population was 212,000" — never a bare present tense for a moving fact.
- **Attribute anything evaluative.** "According to the 2025 audit report…", "The WHO recommends…", "Critics in *Le Monde* argued…" — beats "It is known that…", "Experts agree…", "It is widely believed…".
- **Neutral vocabulary.** Not "groundbreaking", "controversial", "renowned", "infamous", "so-called"; if a source says it and it matters, quote and attribute.
- **No text for the reader or for agents.** No "note that", "see below", "as an AI", no instructions, no questions.
- **No synthesis.** Two facts from two sources may sit in two sentences; the conclusion that joins them is not yours to write. The only derived numbers are trivial, reproducible and marked ("… equivalent to 3.2 km").

### Before and after

| Weak | Better |
|---|---|
| The bridge is one of the longest in Europe.[^c1] | At 2,682 m, the bridge was the third-longest cable-stayed bridge in Europe when it opened in 2004.[^c1] ^c1 |
| The drug is effective against migraine.[^c2] | A 2023 Cochrane review of 12 trials (4,100 participants) found the drug reduced monthly migraine days by 1.8 on average compared with placebo.[^c2] ^c2 |
| The minister was criticised for the decision.[^c3] | The opposition leader called the decision "reckless" in parliament on 4 May 2025.[^c3] ^c3 |
| The city has a population of 500,000.[^c4] | As of the 2021 census the city had 498,312 inhabitants.[^c4] ^c4 |
| Experts consider the site authentic.[^c5] | The 2019 excavation report by the national heritage institute dates the site to the 3rd century BCE.[^c5] ^c5 |

## Demonstrated sentences

When a sentence is a theorem, a computation or a derivation (C10), write it so the reader sees it is derived and from what: "By the Clausius–Clapeyron relation[^c3] and the cited enthalpy of vaporisation[^c4], water boils at about 81 °C at 0.5 atm.[^c5] ^c5" — c3 and c4 are sourced premises, c5 is the demonstrated claim whose demonstration shows the calculation. State the scope in the sentence when it is not obvious ("in the ideal-gas approximation", "for all integers n ≥ 1"). Never write a derived number with more precision than its inputs carry.

## Markup

Articles use the Scio Markdown dialect ([markdown.md](markdown.md)): typed front matter, one sentence per line ending in `[^cN] ^cN`, `[[wikilinks]]` for navigation, `![[slug^cN]]` to reuse a claim from another article, `> [!disputed]` for disagreement. No raw HTML, no external links in prose.

## Structure

- **Lead**: what it is, why it matters, the three to five facts a reader needs first — each with its claim. A reader who stops after the lead should have the essentials right.
- **Summary** (front matter): at most three sentences from the lead, 1,200 characters in all, each ending in the marker of the claim the lead cites for it. Search serves it free, so it carries the same evidence as the body. Write abbreviations out ("Doctor Smith", not "Dr. Smith"): there every period before a space ends a sentence ([markdown.md](markdown.md) §2a).
- **Sections by aspect**, in the order a reference work would use for that kind of subject (a person: life, work, reception; a place: geography, history, economy, demographics; a concept: definition, history, applications, criticism). Headings carry no claims.
- **Disagreement gets its own sentences**: two lines, `X reports A.[^c6] ^c6` and `Y reports B.[^c7] ^c7`, inside a `> [!disputed]` callout — not a blended average, not a silent choice.
- **What is not known** is worth a sentence when sources say so: `The cause of the 1911 fire was never established.[^c8] ^c8`
- **References are generated from claims**; do not hand-write a references section. `[[Wikilinks]]` to other Scio articles are navigation, not sources; a link to a missing article is fine — it registers demand for the gap.
- **Length** follows the sourced facts. A good 400-word article beats a padded 2,000-word one; a subject with fifty facts deserves fifty sentences.

## Language

Write in the target `lang`, in the register of a serious reference work in that language. Keep proper names in their original script with a transliteration on first mention. Localise units and date formats to the language's conventions; keep the source's figures exact. Define terms at first use or link to the article that defines them.
