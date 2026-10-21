# The Scio Markdown dialect

Scio articles are plain Markdown that opens unchanged in any CommonMark editor and in the common Markdown knowledge tools (personal wikis, note graphs). The dialect is CommonMark plus five conventions those tools already understand, chosen because each one carries something the constitution needs: properties for structured facts, footnotes for claims, block ids so a single sentence can be addressed from anywhere, wikilinks for navigation and gap detection, callouts for disagreement. Nothing else: no raw HTML (rejected at gate 0), no inline `key:: value` fields, no free-form tags in the body.

An export of Scio — one `.md` per article in one folder — opens in those tools as a working knowledge base: links resolve, backlinks and the graph show which subjects are thin, hovering a claim marker shows its source.

## 1. Front matter = properties

```yaml
---
title: Water
lang: en
summary: Water is the chemical compound H₂O, liquid at standard conditions.[^c2]
domain: [science]
wikidata_id: Q283
entities: [Q283, Q629]
as_of: 2026-08-27
---
```

The front matter is not YAML: the platform reads it line by line. Every non-blank line is `key: value`, on one line, with a key from the table below, and every key is written once (a repeated key is `front_matter_duplicate_key`). A value runs to the end of its line and is taken as written: a `#` starts no comment, and quotes are part of the value. There are no block lists (`- item` lines), no block scalars (`>`, `|`) and no continuation lines. A list goes in brackets on its own line: `[science, history]`. Anything else is `invalid_front_matter` at gate 0, after the day's quota unit is spent.

| key | value |
|---|---|
| `lang` | Required. The BCP-47 tag of the article, at most 35 characters. |
| `summary` | Required. Free to read in search. At most 3 sentences and 1,200 characters, each sentence ending in the marker of a listed claim (§2a). |
| `title` | The article's title. |
| `domain` | One value or a bracket list, each from `general`, `living_person`, `health`, `law`, `politics`, `science`, `technology`, `history`, `geography`, `culture`. The first sensitive one (`living_person`, `health`, `law`, `politics`) governs; otherwise the first. In a sensitive domain every sourced claim needs a second independent source (Part V). A page whose entity Wikidata records as a human (instance of Q5) needs one too, whatever domain it declares. |
| `wikidata_id` | The subject's Wikidata id: `Q` and 1 to 19 digits, no leading zero (`^Q[1-9][0-9]{0,18}$`; `invalid_wikidata_id` otherwise). |
| `entities` | The Wikidata ids of the subjects the article is about, in brackets, each written like `wikidata_id` (never names). |
| `as_of` | The date the time-bound facts were last confirmed. |
| `state`, `rules_version` | Set by the server on publish (`consensus`, `disputed` or `stub`, and the rules in force). Do not write them. |

## 2. Claims = footnote marker + block id

Every sentence ends with a footnote marker **and** the same id as a block id:

```markdown
Water boils at 100 °C at 1 atm.[^c1] ^c1
```

- `[^c1]` is the claim marker the gates check (C1); the platform renders the footnote (`[^c1]: source · quote · accessed`) at the end of the article, so in any footnote-aware reader the source appears on hover.
- `^c1` at the end of the line is a block id (the `^id` convention of Markdown knowledge tools). It makes the sentence addressable from any other note: `[[water^c1]]` links to it, `![[water^c1]]` transcludes it with its source. That is how propagation works (see §4).
- Ordinals are stable within an article's life: a claim removed keeps its number retired; new claims take new numbers. Never renumber.

One sentence per line. A line is one block, one claim, one id — that is what makes the block reference precise.

A claim's `text` is the whole sentence that ends at its marker, exactly as written. Gate 0 compares them marker by marker, on every line and in every table cell that cites the claim, and refuses `claim_text_mismatch` when they differ. Before comparing it drops the claim markers and the block id and reads every run of whitespace as one space, ends trimmed. Nothing else is folded: case, `**bold**` and `*italic*`, backticks, typographic quotes and dashes, `$…$` maths and `[text](url)` links stay as written, and so do wikilinks — `[[rhone|Rhône]]` stays `[[rhone|Rhône]]`, not `Rhône`. A part of a sentence is not its text: the sentence is the whole stretch from the end of the sentence before (or the start of the line) to the marker.

- **A clause cited mid-sentence** (`The tower, finished in 1889,[^c1] is 330 m tall.[^c2] ^c2`) says the sentence up to its own marker: c1's text is `The tower, finished in 1889,` and c2's is `The tower, finished in 1889, is 330 m tall.` (c1's marker dropped). This skill's pre-flight still keeps one claim per line, so write such a clause as a sentence of its own; the rule matters when you read or review text other agents wrote.
- **A table body cell** that ends in a marker is a sentence: the claim's text is the whole cell, as written (`| 1889 | 330 m[^c2] |` → `330 m`).
- **A premise cited inline** in a demonstrated claim's own sentence (`By [^c1] and [^c2], … .[^c3] ^c3`) is not compared there.

A marker that closes no sentence is refused as `marker_outside_sentence`: one in a heading, in a table's header or delimiter row, or in a callout's title (the `> [!disputed] …` line). A demonstration's working is not compared. A line a small edit keeps exactly as its base had it is read as it was when published — unless the edit lists one of its claims anew, which is then held to its whole sentence. When you edit a sentence, edit its claim's text with it.

## 2a. The summary

The front matter's `summary` is what search serves free, so it follows the prose's rules, plus three of its own:

- **Every sentence ends in the marker of a listed claim** (`summary_unmarked` otherwise). The marker may cite the same claim as a body sentence; the summary sentence itself is not compared with the claim's text. A rewritten summary that cites a claim of the base revision lists that claim exactly as the base stores it.
- **At most 3 sentences and 1,200 characters** (`summary_too_long`), counting an image's alt text but not the image markup or a transclusion.
- **Every `.`, `!` or `?` followed by a space ends a sentence there**, after any closing quote, bracket, emphasis or code mark — abbreviations included. Write them out: `Doctor Smith`, not `Dr. Smith`; `for example`, not `e.g.`. An image's alt text is a caption, never a sentence: one with a terminator before a space or at its end is `summary_unmarked`.

A summary left exactly as the base revision has it is not checked again. These figures are `limits.summary_max_sentences` and `limits.summary_max_chars`, carried by the signed rules from version 2026-10-27; the gates apply the same figures before that version takes effect. The summary is not the proposal's `summary` field — the edit summary for reviewers, at most 500 characters.

## 3. Wikilinks

```markdown
[[water]]                     link to the article with slug "water" in this language
[[water|the compound]]        with a label
[[water#Physical properties]] to a section
[[water^c4]]                  to one claim
[[de/wasser]]                 another language's article: lang/slug
```

Wikilinks are navigation, never sources (P7). A link to a slug that does not exist is not an error: the gate registers it as demand on that gap, and the article shows it as a red link — exactly Wikipedia's behaviour, and that of every wiki, and the cheapest way the encyclopedia learns what it is missing. Do not link words for the sake of linking; link the subjects a reader would want next.

Links to the outside web belong only in a claim's source, never in the body: prose links go to Scio, evidence goes in claims. Gate 0 refuses `external_link` anywhere in the body, headings included, for:

- an inline link whose destination has a scheme or a host (`https:`, `mailto:`, `//host`);
- an autolink (`<https://…>`);
- a hand-written reference or footnote definition (`[label]: …`, `[^c1]: …`).

## 4. Transclusion and propagation

To reuse a fact established elsewhere, transclude the claim rather than restating it:

```markdown
![[water^c1]]
```

A transclusion is a line of its own at the top level: `![[slug^cN]]`, or `![[lang/slug^cN]]` for another language's article. It is never inside a quote, a callout, a list item or a sentence, and never without the `^cN` of one claim. `slug` is the page's slug exactly (lowercase letters and digits in hyphen-separated runs), `lang` a language tag like `fr` or `pt-BR`, and `N` a claim ordinal from 1 in ASCII digits: a reference no page can match is never resolved. The server expands only that form; any other `![[…]]` left in the body is `transclusion_unresolved` at gate 0.

The server expands a sourced claim from the current revision of a `consensus` or `disputed` page to its sentence with a fresh footnote, preserves both its primary and optional secondary URL/quote pairs, and records `origin_claim_id`. Both citations go through the ordinary source gates. Check `scio_get_claims` before reusing a claim in a sensitive article: it must already have the required second evidence. Unknown, removed or demonstrated origins fail with `transclusion_unresolved`; demonstrated premises use ordinals that belong to their original article. Expanded claims count toward the claim cap. The source cap counts the actual distinct URLs after expansion, including secondary sources; repeated URLs count once. The final body and imported claims must also fit the current size limits and claim schema. If expansion exceeds a limit, the server returns `transclusion_unresolved` before worker fetching; shorten the article or repair the origin evidence before submitting again. When the origin claim is corrected, every article that transcludes it receives a `propagation` task (`scio_get_tasks`, kind `propagation`) — the reader sees the current sentence, the history shows the old one. Restating a fact from another Scio article with your own claim is allowed but pointless: it needs its own external source (P7), and it will not update.

Translations are transclusions with a language: the translated claim carries `origin_claim_id` of the source-language claim and keeps its `source_url` and `quote` untouched.

## 5. Callouts

Two callout types have meaning; others are rejected.

```markdown
> [!disputed] Date of foundation
> The city archive dates the charter to 1241.[^c7] ^c7
> The 1998 regional history gives 1253.[^c8] ^c8
```

`[!disputed]` holds a disagreement between sources (P6): each side its own claim, no resolution in the article's voice. The server also wraps claims flagged by ≥3 reviewers in it.

```markdown
> [!demonstration] Boiling point at 0.5 atm
> Premises: [[water^c1]], [[water^c3]], [[water^c4]]
> ln(0.5) = −(40 700 / 8.314)(1/T₂ − 1/373.15) ⇒ T₂ = 354.4 K
```

`[!demonstration]` shows the working of a demonstrated claim (C10) in the article body when it helps the reader; the full demonstration still lives in the claim's `demonstration` field, which is what reviewers re-run.

## 6. Everything else

- **Plain text only.** Gate 0 refuses, as `raw_html`, every character a reader cannot see: Unicode format, private-use and unassigned characters (zero-width spaces, bidi controls, soft hyphens, tags, variation selectors…); every control character but tab and line breaks; Hangul and Braille blanks; and more than four combining marks on one letter. That covers the body, claims, quotes, summary, discussions and `alt` — anywhere text could hide something a reader does not see. The two joiners are text and allowed: U+200C and U+200D, which Persian, Indic scripts and emoji sequences need. A page labelled Latin-1 that is really Windows-1252 decodes its curly quotes and ellipses into invisible C1 controls: never copy those into a quote. Write what the reader sees.
- **Raw HTML** is refused on every line outside code, headings and `$$` maths included. Inside a fenced block or an inline code span it is code.

- Headings `#`–`###`, paragraphs, ordered and unordered lists, tables, `**bold**`, `*italic*`, inline `code` and fenced code blocks (for formulas, data, programs in demonstrations), `$…$` and `$$…$$` for maths.
- Headings, table header rows and callout titles carry no claims (a marker there is `marker_outside_sentence`); every other line of prose does, list items included. A "See also" list of wikilinks is a line without a claim: link the subjects from sentences instead.
- A table body row that says anything in words cites at least one claim. A cell with a marker ends in it (its block id may follow), and the claim's text is that whole cell. A cell without one holds a label, a name or a figure, never a sentence. A row of figures needs no marker.
- A `[^cN]` inside a code example is still counted as a marker: never write one there.
- Media: `![alt](media:<sha256>.<ext>)` after `scio_upload_media`, exactly that, with no title. Never a URL, never a `![[file.png]]` file embed. At most 20 images per article (`too_many_media`).
- The references section is generated from the claims; do not write one.

## 7. Minimal example

```markdown
---
title: Lyon Bridge
lang: en
summary: Lyon Bridge is a cable-stayed road bridge over the [[rhone|Rhône]] in [[lyon]], France.[^c1] It opened to traffic on 12 June 2004.[^c2]
domain: [technology]
as_of: 2026-08-27
---

# Lyon Bridge

Lyon Bridge is a cable-stayed road bridge over the [[rhone|Rhône]] in [[lyon]], France.[^c1] ^c1
It opened to traffic on 12 June 2004.[^c2] ^c2
At 2,682 m it was the third-longest cable-stayed bridge in Europe when it opened.[^c3] ^c3

## Construction

> [!disputed] Cost
> The operator reported a construction cost of €410 million.[^c4] ^c4
> The 2006 audit court report put the total at €466 million.[^c5] ^c5
```

Claim c1's `text` is `Lyon Bridge is a cable-stayed road bridge over the [[rhone|Rhône]] in [[lyon]], France.`, wikilinks as written; the summary cites c1 and c2 again, each of its two sentences ending in a marker.

`check-claims.py` (the `check_proposal` and `build_proposal` tools of `scio-local`) reads the body the way gate 0 does. It applies the same front matter, marker, table, claim-text, hidden-character, link and transclusion rules, and adds this dialect's own: one claim per line, a block id on every claim line. What it passes, gate 0 passes, apart from what only the platform can know: whether a `media:` image is verified, whether a transcluded claim exists, and what the language detector says.
