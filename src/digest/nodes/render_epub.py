"""Render node: build the EPUB journal (table of contents, sections, links to sources).

Deterministic layout: a script, no LLM.
"""

import html
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from ebooklib import epub

from digest.paths import ROOT
from digest.state import Article, DigestState, NodeMetrics

OUT_DIR = ROOT / "out"
SECTIONS = {"data": "Data & IA", "monde": "Monde", "eco": "Économie", "france": "France"}
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
CSS = "h1 { font-size: 1.4em; } h2 { font-size: 1.15em; margin-top: 1.6em; } .meta { color: #555; }"


def french_date(day: datetime) -> str:
    # Written by hand: strftime would depend on the machine's locale.
    return f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def article_html(article: Article) -> str:
    parts = [
        f"<h2>{esc(article.title)}</h2>",
        f'<p class="meta">{esc(article.source)} · note {article.score}/10</p>',
    ]
    if article.summary:
        parts.append(f"<p>{esc(article.summary)}</p>")
        if article.why_it_matters:
            parts.append(f"<p><b>Pourquoi c'est important :</b> {esc(article.why_it_matters)}</p>")
    elif article.snippet:
        # No summary (unreadable page or failed call): the source's own snippet, nothing invented.
        parts.append(f"<p>{esc(article.snippet)}</p>")
        parts.append('<p class="meta">Chapô de la source, sans résumé.</p>')
    else:
        # Neither summary nor snippet (most Hacker News links): say so, rather than announce a
        # snippet that does not exist (seen in the journal of 2026-11-15).
        parts.append('<p class="meta">Ni résumé ni chapô pour cet article : seul le titre est '
                     "disponible.</p>")
    parts.append(f'<p><a href="{esc(article.url)}">Lire l\'article</a></p>')
    return "\n".join(parts)


def raw_post_html(article: Article) -> str:
    """A Reddit post as its author wrote it: no summary, paragraphs kept."""
    parts = [
        f"<h2>{esc(article.title)}</h2>",
        f'<p class="meta">{esc(article.source)} · tel qu\'écrit</p>',
    ]
    paragraphs = [p for p in article.text.split("\n\n") if p]
    if paragraphs:
        parts += [f"<p>{esc(p)}</p>" for p in paragraphs]
    else:
        parts.append('<p class="meta">Lien sans texte.</p>')
    parts.append(f'<p><a href="{esc(article.url)}">Voir la discussion</a></p>')
    return "\n".join(parts)


def report_html(state: DigestState) -> str:
    """Last page: what this journal cost and what went wrong."""
    calls = state.get("llm_calls", [])
    errors = state.get("errors", [])
    raw_posts = [a for a in state.get("selected", []) if a.raw]
    lines = [
        "<h1>Bilan du jour</h1>",
        (
            f"<p>{len(state.get('collected', []))} articles collectés, "
            f"{len(state.get('cleaned', []))} après nettoyage, "
            f"{len(state.get('summarized', []))} résumés et {len(raw_posts)} posts bruts.</p>"
        ),
        f"<p>{len(calls)} appels au modèle, coût total : {sum(c.cost_usd for c in calls):.4f} $.</p>",
    ]
    if errors:
        items = "".join(f"<li>{esc(e.source)} : {esc(e.error)}</li>" for e in errors)
        lines.append(f"<p>Incidents :</p><ul>{items}</ul>")
    else:
        lines.append("<p>Aucun incident.</p>")
    return "\n".join(lines)


def build_book(state: DigestState, today: datetime) -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier(f"kindle-digest-{today:%Y-%m-%d}")
    book.set_title(f"Journal du {french_date(today)}")
    book.set_language("fr")
    book.add_author("Kindle Digest")
    style = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(style)

    def chapter(title: str, file_name: str, content: str) -> epub.EpubHtml:
        page = epub.EpubHtml(title=title, file_name=file_name, lang="fr")
        page.content = content
        page.add_item(style)
        return page

    chapters = []
    articles = state.get("summarized", [])
    raw_posts = [a for a in state.get("selected", []) if a.raw]
    for key, name in SECTIONS.items():
        in_section = sorted(
            (a for a in articles if a.section == key), key=lambda a: a.score or 0, reverse=True
        )
        if in_section:
            body = "\n".join(map(article_html, in_section))
            chapters.append(chapter(name, f"{key}.xhtml", f"<h1>{esc(name)}</h1>\n{body}"))
        if key == "data" and raw_posts:  # Reddit posts right after Data & IA
            body = "\n".join(map(raw_post_html, raw_posts))
            chapters.append(chapter("Reddit", "reddit.xhtml", f"<h1>Reddit</h1>\n{body}"))
    chapters.append(chapter("Bilan du jour", "bilan.xhtml", report_html(state)))

    for chapter in chapters:
        book.add_item(chapter)
    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]
    return book


def render_epub(state: DigestState) -> dict:
    start = time.perf_counter()
    today = datetime.now(ZoneInfo("Europe/Paris"))
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"digest-{today:%Y-%m-%d}.epub"
    epub.write_epub(path, build_book(state, today))

    metrics = NodeMetrics(
        "render_epub",
        round(time.perf_counter() - start, 3),
        {
            "articles": len(state.get("summarized", [])),
            "raw_posts": sum(a.raw for a in state.get("selected", [])),
            "size_bytes": path.stat().st_size,
        },
    )
    return {"epub_path": str(path), "metrics": [metrics]}
