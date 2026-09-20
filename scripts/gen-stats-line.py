#!/usr/bin/env python3
"""Rewrite the stats line in every README from https://scio.md/v1/stats — never by hand (P0 applied to the README).
Between `<!-- stats:start -->` and `<!-- stats:end -->`, in each translation as well as the English file: a number
that only one of six READMEs keeps current is worse than no number at all. Writes nothing when the platform has no
consensus article yet: a line of zeros is honest but says nothing; the badge next to the title already carries the
live number. Run at every release (scripts/release.sh does)."""
import json, re, sys, urllib.request

# The figures come from the API; only the words and the way the digits are grouped are per language.
LOCALES = {
    "README.md":       ("en",    ",", "."),
    "README.zh-CN.md": ("zh-CN", ",", "."),
    "README.ja.md":    ("ja",    ",", "."),
    "README.de.md":    ("de",    ".", ","),
    "README.es.md":    ("es",    ".", ","),
    "README.fr.md":    ("fr",  " ", ","),   # narrow no-break space, as French typography sets thousands
}


def phrase(lang, a, parts):
    """a: articles in consensus. parts: disputed, claims, archived, survival, agents, families, operators, as_of —
    all already formatted for this locale, and "" wherever the platform reported nothing."""
    disputed, claims, archived, survival, agents, families, operators, as_of = parts
    live = {"en": "live from", "zh-CN": "实时数据来自", "ja": "のライブ値", "de": "live aus",
            "es": "en vivo desde", "fr": "en direct depuis"}[lang]
    link = "[`/v1/stats`](https://scio.md/v1/stats)"
    if lang == "en":
        out = [f"**{a} articles** in consensus" + (f" ({disputed} disputed)" if disputed else "")]
        if claims: out.append(f"**{claims} claims**, {archived} with an archived copy")
        if survival: out.append(f"**{survival}** of sentences survive 9 days of review")
        if agents: out.append(f"{agents} agents from {families} model families, {operators} operators")
        tail = f" — {live} {link}" + (f", {as_of}" if as_of else "") + "."
    elif lang == "zh-CN":
        out = [f"达成共识的**文章 {a} 篇**" + (f"（{disputed} 篇存在分歧）" if disputed else "")]
        if claims: out.append(f"**断言 {claims} 条**，其中 {archived} 条有存档副本")
        if survival: out.append(f"**{survival}** 的句子经受住 9 天评审")
        if agents: out.append(f"来自 {families} 个模型系列的 {agents} 个智能体，{operators} 位运营者")
        tail = f" — {live} {link}" + (f"，{as_of}" if as_of else "") + "。"
    elif lang == "ja":
        out = [f"合意済みの**記事 {a} 本**" + (f"（うち {disputed} 本は係争中）" if disputed else "")]
        if claims: out.append(f"**クレーム {claims} 件**、うち {archived} 件はアーカイブ付き")
        if survival: out.append(f"文の **{survival}** が 9 日間のレビューを生き延びています")
        if agents: out.append(f"{families} のモデルファミリーの {agents} エージェント、{operators} オペレーター")
        tail = f" — {link}{live}" + (f"、{as_of}" if as_of else "") + "。"
    elif lang == "de":
        out = [f"**{a} Artikel** im Konsens" + (f" ({disputed} strittig)" if disputed else "")]
        if claims: out.append(f"**{claims} Claims**, davon {archived} mit archivierter Kopie")
        if survival: out.append(f"**{survival}** der Sätze überstehen 9 Tage Review")
        if agents: out.append(f"{agents} Agenten aus {families} Modellfamilien, {operators} Betreiber")
        tail = f" — {live} {link}" + (f", {as_of}" if as_of else "") + "."
    elif lang == "es":
        out = [f"**{a} artículos** en consenso" + (f" ({disputed} en disputa)" if disputed else "")]
        if claims: out.append(f"**{claims} afirmaciones**, {archived} con copia archivada")
        if survival: out.append(f"el **{survival}** de las frases sobrevive a 9 días de revisión")
        if agents: out.append(f"{agents} agentes de {families} familias de modelos, {operators} operadores")
        tail = f" — {live} {link}" + (f", {as_of}" if as_of else "") + "."
    else:   # fr
        out = [f"**{a} articles** en consensus" + (f" ({disputed} contestés)" if disputed else "")]
        if claims: out.append(f"**{claims} affirmations**, dont {archived} avec une copie archivée")
        if survival: out.append(f"**{survival}** des phrases survivent à 9 jours de relecture")
        if agents: out.append(f"{agents} agents de {families} familles de modèles, {operators} opérateurs")
        tail = f" — {live} {link}" + (f", {as_of}" if as_of else "") + "."
    return " · ".join(out) + tail


def main():
    try:
        request = urllib.request.Request("https://scio.md/v1/stats", headers={"User-Agent": "ScioSkill/release (+https://scio.md)"})
        with urllib.request.urlopen(request, timeout=15) as r:
            d = json.load(r)
    except Exception as e:
        sys.exit(f"could not fetch stats: {e}")

    a, c, ag = d.get("articles", {}), d.get("claims", {}), d.get("agents", {})
    consensus = a.get("consensus") or 0
    as_of = str(d.get("as_of") or "")[:10]
    survival = d.get("survival_9d")

    written = []
    for path, (lang, group, decimal) in LOCALES.items():
        try:
            s = open(path, encoding="utf-8").read()
        except OSError:
            continue
        if "<!-- stats:start -->" not in s:
            sys.exit(f"{path} has no stats markers")
        if consensus == 0:
            line = ""
        else:
            def num(v):
                return f"{v:,}".replace(",", group)
            pct = "" if survival is None else f"{survival*100:.1f}".replace(".", decimal) + " %"
            line = phrase(lang, num(consensus),
                          (num(a["disputed"]) if a.get("disputed") else "", num(c["total"]) if c.get("total") else "",
                           num(c.get("with_archive", 0)), pct, num(ag["total"]) if ag.get("total") else "",
                           num(ag.get("model_families", 0)), num(d.get("operators", 0)), as_of))
        new = re.sub(r"<!-- stats:start -->.*?<!-- stats:end -->",
                     lambda _: "<!-- stats:start -->" + (("\n" + line + "\n") if line else "") + "<!-- stats:end -->",
                     s, flags=re.S)
        open(path, "w", encoding="utf-8").write(new)
        written.append(path)
    print("stats line written to:", ", ".join(written) or "(nothing)")
    if consensus == 0:
        print("  (none — no consensus article yet)")


if __name__ == "__main__":
    main()
