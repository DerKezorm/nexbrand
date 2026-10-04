"""Collecting a brand from where it already lives: a website, a GitHub repository, a PDF style guide.

**Measured, never guessed.** Every colour here was found in a page's styles, a repository's files or a PDF's text,
with how much it weighs (a background counts more than a border) and the names it was found under (a CSS variable, a
Tailwind key, the words beside it in a style guide). Sorting into roles is then done by rules, or by the account's AI
when it has one switched on; the AI may name, sort and drop, but a value it did not get is thrown away
(``order_with_ai``). The result is a proposal; nothing is stored until a person makes a draft of it.

Fonts are recorded by name. Only fonts known to be free (Google Fonts, Fontsource) say so; a font a site hosts itself
has a licence nobody here knows, and its files are never fetched.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from . import colors, outbound

logger = logging.getLogger("nexbrand.collect")

MAX_PAGE = 2 * 1024 * 1024
MAX_SHEET = 1024 * 1024
MAX_SHEETS = 10
MAX_REPO_FILES = 40
MAX_REPO_BYTES = 4 * 1024 * 1024
MAX_PDF_PAGES = 80
MAX_COLORS = 40

# --- Colour values in text -------------------------------------------------------------------------------------------

_HEX = re.compile(r"#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_-])")
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})(?:\s*[,/]\s*([\d.]+%?))?\s*\)", re.IGNORECASE)
_HSL = re.compile(r"hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%(?:\s*[,/]\s*([\d.]+%?))?\s*\)",
                  re.IGNORECASE)
_DECL = re.compile(r"([a-zA-Z-][a-zA-Z0-9-]*)\s*:\s*([^;{}]+)")
_FONT_FACE = re.compile(r"@font-face\s*{([^}]*)}", re.IGNORECASE)
_GENERIC = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "-apple-system",
            "blinkmacsystemfont", "inherit", "initial", "unset", "ui-sans-serif", "ui-serif", "ui-monospace", "emoji",
            "math", "revert"}


def _alpha_ok(value: str | None) -> bool:
    if not value:
        return True
    try:
        number = float(value.rstrip("%"))
    except ValueError:
        return True
    return (number / 100 if value.endswith("%") else number) >= 0.5


def colors_in(text: str) -> list[str]:
    """Every colour value written in a piece of CSS or text, as ``#RRGGBB``; nearly transparent ones left out."""
    found: list[str] = []
    for match in _HEX.finditer(text):
        raw = match.group(1)
        if len(raw) in (3, 4):
            raw = "".join(char * 2 for char in raw)
        if len(raw) == 8 and int(raw[6:], 16) < 128:
            continue
        found.append("#" + raw[:6].upper())
    for match in _RGB.finditer(text):
        r, g, b = (int(match.group(i)) for i in (1, 2, 3))
        if max(r, g, b) <= 255 and _alpha_ok(match.group(4)):
            found.append(colors.to_hex((r, g, b)))
    for match in _HSL.finditer(text):
        h, s, lightness = (float(match.group(i)) for i in (1, 2, 3))
        if s <= 100 and lightness <= 100 and _alpha_ok(match.group(4)):
            found.append(colors.from_hsl(h % 360, s, lightness))
    return found


def _weight(prop: str) -> float:
    prop = prop.lower()
    if prop.startswith("--"):
        return 2.0
    if prop.startswith("background") or prop in ("fill", "accent-color"):
        return 3.0
    if prop == "color":
        return 2.0
    return 1.0


#: Fonts that are no house font: symbols (FontAwesome and friends) and code. Left out of what was found.
_ICON_FONT = re.compile(r"awesome|icon|glyph|symbols|dashicons|icomoon|feather|themify|linearicons|elegant",
                        re.IGNORECASE)
_CODE_FIRST = {"sfmono-regular", "sf mono", "menlo", "monaco", "consolas", "liberation mono", "courier new", "courier",
               "ui-monospace", "monospace", "source code pro", "fira code", "jetbrains mono"}
#: A stack that starts like this is the device's own font (Bootstrap and most frameworks), not a font of the brand.
_SYSTEM_FIRST = {"-apple-system", "system-ui", "blinkmacsystemfont", "ui-sans-serif", "ui-serif"}
_SIZE = re.compile(r"(?:^|\s)(?:\d*\.?\d+(?:px|em|rem|%|pt|pc|ex|ch|vw|vh|vmin|vmax)|0|xx-small|x-small|small|medium|"
                   r"large|x-large|xx-large|smaller|larger)(?:\s*/\s*\S+)?\s+(.+)$", re.IGNORECASE)


#: A style sheet of a framework (its colours are the framework's, not the brand's), by its file name.
_FRAMEWORK_SHEET = re.compile(
    r"(?:^|[/._-])(bootstrap|tailwind|foundation|bulma|materialize|uikit|semantic)[^/]*\.css$",
    re.IGNORECASE,
)
#: The colours Bootstrap 4 and 5 bring along (theme, greys, alerts, tables, focus): a page that bundles Bootstrap into
#: its own style sheet carries them too. Marked and left out; a person ticks one back when it is the brand's after all.
FRAMEWORK_COLORS = frozenset([
    "#007BFF", "#6610F2", "#6F42C1", "#E83E8C", "#DC3545", "#FD7E14", "#FFC107", "#28A745", "#20C997", "#17A2B8",
    "#6C757D", "#343A40", "#F8F9FA", "#0056B3", "#80BDFF", "#DEE2E6", "#E9ECEF", "#CED4DA", "#ADB5BD", "#495057",
    "#212529", "#868E96", "#004085", "#CCE5FF", "#B8DAFF", "#383D41", "#E2E3E5", "#D6D8DB", "#155724", "#D4EDDA",
    "#C3E6CB", "#0C5460", "#D1ECF1", "#BEE5EB", "#856404", "#FFF3CD", "#FFEEBA", "#721C24", "#F8D7DA", "#F5C6CB",
    "#818182", "#FEFEFE", "#FDFDFE", "#1B1E21", "#D6D8D9", "#C6C8CA", "#9FCDFF", "#B3B7BB", "#8FD19E", "#86CFDA",
    "#FFDF7E", "#ED969E", "#FBFCFC", "#95999C", "#ECECF6", "#B9BBBE", "#F1B0B7", "#FFE8A1", "#ABDDE5", "#B1DFBB",
    "#0D6EFD", "#D63384", "#198754", "#0DCAF0", "#0A58CA", "#86B7FE", "#CFE2FF", "#084298", "#B6D4FE", "#D1E7DD",
    "#0F5132", "#BADBCC", "#842029", "#F5C2C7", "#664D03", "#FFECB5", "#CFF4FC", "#055160", "#B6EFFB", "#41464B",
    "#D3D6D8", "#141619", "#BCBEBF", "#E2E3E5", "#6EA8FE", "#DEE2E6",
])


def _names(value: str) -> list[str]:
    return [part.strip().strip("'\"").strip() for part in value.split(",") if part.strip()]


def _first_family(value: str) -> str | None:
    for name in _names(value):
        if name and name.lower() not in _GENERIC and not name.lower().startswith("var("):
            return name[:80]
    return None


def _shorthand_families(value: str) -> str | None:
    """The family list of a ``font:`` shorthand: what follows the size (and the line height after a slash). A
    shorthand without a size names no family (``font: inherit``, ``font: caption``)."""
    found = _SIZE.search(value.strip())
    return found.group(1) if found else None


def _kind_of_stack(value: str) -> str:
    """``system`` for the device's own font, ``code`` for a code font, ``icon`` for a symbol font, else ``font``."""
    names = [name.lower() for name in _names(value)]
    if not names:
        return "font"
    if names[0] in _SYSTEM_FIRST:
        return "system"
    if names[0] in _CODE_FIRST:
        return "code"
    if _ICON_FONT.search(names[0]):
        return "icon"
    return "font"


@dataclass
class Found:
    """What one or more sources gave, before sorting."""

    colors: dict[str, dict[str, Any]] = field(default_factory=dict)
    fonts: dict[str, dict[str, Any]] = field(default_factory=dict)
    logos: list[dict[str, str]] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)
    #: The device's own font, when a page uses it (a stack like ``-apple-system, Segoe UI, Roboto``): named, not
    #: offered as a font of the brand.
    system_font: str = ""

    def color(self, hexvalue: str, weight: float, where: str, *, name: str = "", detail: str = "", pantone: str = "",
              cmyk: str = "", framework: bool = False) -> None:
        entry = self.colors.setdefault(hexvalue, {"hex": hexvalue, "weight": 0.0, "where": set(), "names": [],
                                                  "details": [], "pantone": "", "cmyk": "", "own": 0.0})
        entry["weight"] += weight
        # Weight from the page's own style, not from a framework's sheet: what is left over is the framework's.
        if not framework:
            entry["own"] += weight
        entry["where"].add(where)
        clean = " ".join(name.split())[:60]
        if clean and clean not in entry["names"] and len(entry["names"]) < 6:
            entry["names"].append(clean)
        if detail and detail not in entry["details"] and len(entry["details"]) < 4:
            entry["details"].append(detail[:120])
        entry["pantone"] = entry["pantone"] or pantone[:40]
        entry["cmyk"] = entry["cmyk"] or cmyk[:40]

    def font(self, family: str, weight: float, where: str, *, license: str = "unknown", detail: str = "") -> None:
        entry = self.fonts.setdefault(family.casefold(), {"family": family, "weight": 0.0, "where": set(),
                                                          "license": license, "detail": detail[:120]})
        entry["weight"] += weight
        entry["where"].add(where)
        if license == "free":
            entry["license"] = "free"
        if detail and not entry["detail"]:
            entry["detail"] = detail[:120]

    def font_file(self, family: str, url: str, weight: str, style: str) -> None:
        """Where a file of the font lies (from ``@font-face``): fetched only on request, with the licence confirmed."""
        entry = self.fonts.get(family.casefold())
        if entry is None:
            return
        files = entry.setdefault("files", [])
        known = {(f["weight"], f["style"]) for f in files}
        if (weight, style) not in known and len(files) < MAX_FONT_FILES:
            files.append({"url": url[:500], "weight": weight, "style": style})


#: Files of one font to remember (weights and styles), and the formats in the order taken (the smallest first).
MAX_FONT_FILES = 12
_FORMATS = ("woff2", "woff", "ttf", "otf", "truetype", "opentype")
_SRC_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)(?:\s*format\(\s*['\"]?([\w-]+)['\"]?\s*\))?", re.IGNORECASE)


def _best_src(src: str, base: str) -> str | None:
    """The file to take of a ``src`` list: woff2 before woff before ttf/otf; never data: or a local() font."""
    best: tuple[int, str] | None = None
    for url, fmt in _SRC_URL.findall(src):
        url = url.strip()
        if url.lower().startswith("data:"):
            continue
        kind = (fmt or url.split("?")[0].rsplit(".", 1)[-1]).lower()
        rank = _FORMATS.index(kind) if kind in _FORMATS else len(_FORMATS)
        absolute = urljoin(base, url) if base else url
        if absolute.startswith(("http://", "https://")) and (best is None or rank < best[0]):
            best = (rank, absolute)
    return best[1] if best else None


def read_css(found: Found, css: str, where: str, base: str = "", *, framework: bool = False) -> None:
    for block in _FONT_FACE.finditer(css):
        family = re.search(r"font-family\s*:\s*([^;]+)", block.group(1), re.IGNORECASE)
        if family and _kind_of_stack(family.group(1)) != "font":
            continue
        if family and (name := _first_family(family.group(1))):
            found.font(name, 0.5, where, detail="@font-face")
            src = re.search(r"(?<![-\w])src\s*:\s*([^;]+)", block.group(1), re.IGNORECASE)
            url = _best_src(src.group(1), base) if src else None
            if url:
                weight = re.search(r"font-weight\s*:\s*([^;]+)", block.group(1), re.IGNORECASE)
                style = re.search(r"font-style\s*:\s*([^;]+)", block.group(1), re.IGNORECASE)
                found.font_file(name, url, (weight.group(1).strip() if weight else "400")[:20],
                                (style.group(1).strip() if style else "normal")[:20])
    for match in _DECL.finditer(css):
        prop, value = match.group(1), match.group(2)
        if prop.lower() in ("font-family", "font"):
            stack = _shorthand_families(value) if prop.lower() == "font" else value
            if stack is None:
                continue
            kind = _kind_of_stack(stack)
            if kind == "system":
                found.system_font = found.system_font or ", ".join(_names(stack)[:5])[:120]
            elif kind == "font" and (name := _first_family(stack)) and len(name) > 1:
                found.font(name, 1.0, where, detail=f"font-family: {stack.strip()[:60]}")
            continue
        for hexvalue in colors_in(value):
            name = prop[2:] if prop.startswith("--") else ""
            name = re.sub(r"^(color|colour|clr|brand|theme)-", "", name)
            found.color(hexvalue, _weight(prop), where, name=name.replace("-", " "),
                        detail=f"{prop}: {value.strip()[:60]}", framework=framework)


# --- A website -------------------------------------------------------------------------------------------------------


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sheets: list[str] = []
        self.styles: list[str] = []
        self.inline: list[str] = []
        self.theme: str = ""
        self.logos: list[tuple[str, str]] = []
        self.google: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if a.get("style"):
            self.inline.append(a["style"])
        if tag == "style":
            self._in_style = True
        elif tag == "link":
            rel = a.get("rel", "").lower()
            href = a.get("href", "")
            if "stylesheet" in rel and href:
                if "fonts.googleapis.com" in href:
                    self.google.append(href)
                else:
                    self.sheets.append(href)
            if ("icon" in rel or "apple-touch-icon" in rel) and href:
                self.logos.append((href, "icon"))
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name == "theme-color":
                self.theme = a.get("content", "")
            if name in ("og:image", "og:logo") and a.get("content"):
                self.logos.append((a["content"], "og:image"))
        elif tag == "img":
            marks = " ".join((a.get("src", ""), a.get("alt", ""), a.get("class", ""), a.get("id", ""))).lower()
            if "logo" in marks and a.get("src"):
                self.logos.append((a["src"], "img"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)


def _google_families(href: str) -> list[str]:
    query = parse_qs(urlsplit(href).query)
    names = []
    for value in query.get("family", []):
        for part in value.split("|"):
            names.append(unquote(part.split(":")[0]).replace("+", " ").strip())
    return [n for n in names if n][:10]


def from_website(found: Found, url: str) -> None:
    page = outbound.get(url, limit=MAX_PAGE, accept="text/html")
    if "html" not in page.content_type.lower():
        raise outbound.FetchError("no_page")
    host = urlsplit(page.url).hostname or ""
    where = f"website:{host}"
    parser = _Page()
    parser.feed(page.body.decode("utf-8", errors="replace"))
    if parser.theme:
        for hexvalue in colors_in(parser.theme):
            found.color(hexvalue, 4.0, where, detail="meta theme-color")
    for css in parser.styles:
        read_css(found, css, where, page.url)
    for style in parser.inline[:500]:
        read_css(found, "x{" + style + "}", where)
    google = list(parser.google)
    for href in parser.google:
        for family in _google_families(href):
            found.font(family, 2.0, where, license="free", detail="Google Fonts")
    for href in parser.sheets[:MAX_SHEETS]:
        sheet_url = urljoin(page.url, href)
        try:
            sheet = outbound.get(sheet_url, limit=MAX_SHEET, accept="text/css")
        except outbound.FetchError as exc:
            found.notes.append({"source": sheet_url[:200], "problem": exc.code})
            continue
        css = sheet.body.decode("utf-8", errors="replace")
        for imported in re.findall(r"fonts\.googleapis\.com/css2?\?[^'\")\s]+", css):
            google.append("https://" + imported)
            for family in _google_families("https://" + imported):
                found.font(family, 2.0, where, license="free", detail="Google Fonts")
        read_css(found, css, where, sheet.url, framework=bool(_FRAMEWORK_SHEET.search(urlsplit(sheet.url).path)))
    # Where Google keeps the files of the free fonts named: its stylesheet names them (one per weight and style).
    for href in dict.fromkeys(google[:4]):
        try:
            sheet = outbound.get(urljoin(page.url, href), limit=MAX_SHEET, accept="text/css")
        except outbound.FetchError:
            continue
        read_css(found, sheet.body.decode("utf-8", errors="replace"), where, sheet.url)
    # The same picture under two addresses (a theme folder and the upload folder, say) is offered once: by its file
    # name, without the query.
    seen = set()
    for href, kind in parser.logos:
        absolute = urljoin(page.url, href)
        name = urlsplit(absolute).path.rsplit("/", 1)[-1].lower() or absolute
        if name not in seen and absolute.startswith(("http://", "https://")):
            seen.add(name)
            found.logos.append({"url": absolute[:500], "kind": kind, "where": where})
    found.logos = found.logos[:12]


# --- A GitHub repository ---------------------------------------------------------------------------------------------

_REPO = re.compile(r"^https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/tree/([^/]+)(/.*)?)?/?$")
_WANTED = re.compile(r"(^|/)(tailwind\.config\.(js|cjs|mjs|ts)|package\.json|[^/]*tokens?[^/]*\.json"
                     r"|tokens?/.*\.json|theme[^/]*\.(json|js|ts)|[^/]*\.(css|scss|sass|less))$", re.IGNORECASE)
_SKIP = re.compile(r"(^|/)(node_modules|dist|build|vendor|\.next|coverage|out|public/build)/", re.IGNORECASE)
_TW_COLOR = re.compile(r"""['"]?([A-Za-z][\w-]*)['"]?\s*:\s*['"](#[0-9a-fA-F]{3,8})['"]""")


def _github(path: str, token: str) -> Any:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    answer = outbound.get("https://api.github.com" + path, limit=8 * 1024 * 1024, accept="application/json",
                          headers=headers)
    return json.loads(answer.body)


def _walk_tokens(found: Found, data: Any, where: str, path: list[str]) -> None:
    if isinstance(data, dict):
        value = data.get("$value", data.get("value"))
        if isinstance(value, str) and (hexes := colors_in(value)):
            found.color(hexes[0], 2.0, where, name=" ".join(path[-2:]), detail=".".join(path)[:120])
            return
        for key, inner in list(data.items())[:500]:
            _walk_tokens(found, inner, where, [*path, str(key)])
    elif isinstance(data, str) and path and (hexes := colors_in(data)) and data.strip().startswith(("#", "rgb", "hsl")):
        found.color(hexes[0], 1.5, where, name=" ".join(path[-2:]), detail=".".join(path)[:120])


def from_repo(found: Found, url: str, token: str = "") -> None:
    match = _REPO.match(url.strip())
    if not match:
        raise outbound.FetchError("not_a_repo")
    owner, repo, ref, sub = match.group(1), match.group(2), match.group(3), (match.group(4) or "").strip("/")
    where = f"repo:{owner}/{repo}"
    if not ref:
        ref = str(_github(f"/repos/{owner}/{repo}", token).get("default_branch") or "main")
    tree = _github(f"/repos/{owner}/{repo}/git/trees/{ref}?recursive=1", token).get("tree", [])
    files = [item for item in tree if item.get("type") == "blob" and _WANTED.search(item.get("path", ""))
             and not _SKIP.search(item.get("path", "")) and (not sub or item["path"].startswith(sub + "/"))
             and int(item.get("size") or 0) <= 400 * 1024]
    # Configuration first: it names the colours; then style sheets, smaller first.
    files.sort(key=lambda item: (0 if "tailwind" in item["path"] or "token" in item["path"].lower() else 1,
                                 int(item.get("size") or 0)))
    total = 0
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for item in files[:MAX_REPO_FILES]:
        total += int(item.get("size") or 0)
        if total > MAX_REPO_BYTES:
            break
        path = item["path"]
        try:
            raw = outbound.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}", limit=400 * 1024,
                               headers=headers).body.decode("utf-8", errors="replace")
        except outbound.FetchError as exc:
            found.notes.append({"source": path[:200], "problem": exc.code})
            continue
        name = path.rsplit("/", 1)[-1].lower()
        if name == "package.json":
            try:
                deps = json.loads(raw)
            except ValueError:
                continue
            for dep in {**deps.get("dependencies", {}), **deps.get("devDependencies", {})}:
                if dep.startswith(("@fontsource/", "@fontsource-variable/")):
                    family = dep.split("/", 1)[1].replace("-", " ").title()
                    found.font(family, 2.0, where, license="free", detail=f"package.json: {dep}")
        elif name.endswith(".json"):
            try:
                _walk_tokens(found, json.loads(raw), f"{where}:{path}", [])
            except ValueError:
                continue
        elif name.startswith(("tailwind.config", "theme")):
            for key, value in _TW_COLOR.findall(raw):
                for hexvalue in colors_in(value):
                    found.color(hexvalue, 2.5, where, name=key.replace("-", " "), detail=f"{path}: {key}")
            for family in re.findall(r"fontFamily[^}]*?['\"]([A-Z][\w ]+)['\"]", raw):
                found.font(family, 1.5, where, detail=path)
        else:
            read_css(found, raw, where)


# --- A PDF style guide -----------------------------------------------------------------------------------------------

_PDF_RGB = re.compile(r"\bR\s*:?\s*(\d{1,3})\s*[,/ ]\s*G\s*:?\s*(\d{1,3})\s*[,/ ]\s*B\s*:?\s*(\d{1,3})\b"
                      r"|\bRGB\s*:?\s*(\d{1,3})\s*[,/ ]\s*(\d{1,3})\s*[,/ ]\s*(\d{1,3})\b", re.IGNORECASE)
_PDF_CMYK = re.compile(r"\bC\s*:?\s*(\d{1,3})\s*[,/ ]\s*M\s*:?\s*(\d{1,3})\s*[,/ ]\s*Y\s*:?\s*(\d{1,3})\s*[,/ ]\s*"
                       r"K\s*:?\s*(\d{1,3})\b"
                       r"|\bCMYK\s*:?\s*(\d{1,3})\s*[,/ ]\s*(\d{1,3})\s*[,/ ]\s*(\d{1,3})\s*[,/ ]\s*(\d{1,3})\b",
                       re.IGNORECASE)
_PANTONE = re.compile(r"\b(?:PMS|Pantone)\s*([0-9]{3,4}\s*[A-Z]{0,2}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?\s*[A-Z]?)\b")


def _label(line: str) -> str:
    """The words of a line without its values: often the colour's name in a style guide."""
    text = _HEX.sub(" ", line)
    text = _PDF_RGB.sub(" ", text)
    text = _PDF_CMYK.sub(" ", text)
    text = _PANTONE.sub(" ", text)
    text = re.sub(r"\b(HEX|RGB|CMYK|RAL|HKS|Web|Druck|Print)\b\s*:?", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\w äöüÄÖÜß-]", " ", text)
    return " ".join(text.split())[:40]


def from_pdf(found: Found, path: Any, name: str) -> None:
    from pypdf import PdfReader

    reader = PdfReader(path)
    where = f"pdf:{name[:80]}"
    families: dict[str, int] = defaultdict(int)
    previous = ""
    for page in reader.pages[:MAX_PDF_PAGES]:
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - a broken page of a PDF fails in the parser's own way
            logger.info("A page of a PDF could not be read: %s", type(exc).__name__)
            continue
        for line in text.splitlines():
            line = " ".join(line.split())
            if not line:
                continue
            hexes = colors_in(line) if "#" in line else []
            rgb = _PDF_RGB.search(line)
            cmyk = _PDF_CMYK.search(line)
            pantone = _PANTONE.search(line)
            if rgb and not hexes:
                values = [int(v) for v in rgb.groups() if v is not None]
                if len(values) == 3 and max(values) <= 255:
                    hexes = [colors.to_hex((values[0], values[1], values[2]))]
            if not hexes:
                previous = line
                continue
            label = _label(line) or _label(previous)
            cmyk_text = " ".join(v for v in (cmyk.groups() if cmyk else ()) if v is not None)
            found.color(hexes[0], 3.0, where, name=label, detail=line[:120],
                        pantone=pantone.group(0) if pantone else "", cmyk=cmyk_text)
            previous = line
        try:
            fonts = page.get("/Resources", {}).get("/Font", {})
            for value in fonts.values():
                base = str(value.get_object().get("/BaseFont", "")).lstrip("/")
                base = re.sub(r"^[A-Z]{6}\+", "", base)
                family = re.split(r"[-,]", base)[0]
                family = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", family).strip()
                if family and family.lower() not in ("symbol", "zapfdingbats", "arialmt"):
                    families[family] += 1
        except Exception as exc:  # noqa: BLE001 - fonts are a bonus; a strange resource dictionary costs only them
            logger.info("The fonts of a PDF page could not be read: %s", type(exc).__name__)
            continue
    for family, count in families.items():
        found.font(family, float(count), where, detail="embedded in the PDF")


# --- Merging and sorting ---------------------------------------------------------------------------------------------

_HUE_WORDS = {
    "de": [(15, "Rot"), (45, "Orange"), (70, "Gelb"), (160, "Grün"), (195, "Türkis"), (255, "Blau"), (290, "Violett"),
           (340, "Rosa"), (360, "Rot")],
    "en": [(15, "Red"), (45, "Orange"), (70, "Yellow"), (160, "Green"), (195, "Teal"), (255, "Blue"), (290, "Purple"),
           (340, "Pink"), (360, "Red")],
}
_NEUTRAL_WORDS = {"de": ("Hell", "Grau", "Dunkel"), "en": ("Light", "Grey", "Dark")}


def describe(hexvalue: str, language: str) -> str:
    words = _HUE_WORDS.get(language, _HUE_WORDS["en"])
    neutral = _NEUTRAL_WORDS.get(language, _NEUTRAL_WORDS["en"])
    hue, saturation, lightness = colors.hsl(hexvalue)
    if saturation < 12 or lightness >= 90 or lightness < 8:
        return neutral[0] if lightness > 70 else neutral[2] if lightness < 30 else neutral[1]
    return next(word for limit, word in words if hue < limit)


def merged(found: Found) -> list[dict[str, Any]]:
    """The colours found, near-identical ones (ΔE below 2) taken together, heaviest first, with their share. What a
    framework's sheet uses counts a tenth: a framework's many buttons must not make one of its colours the brand's."""
    def counted(entry: dict[str, Any]) -> dict[str, Any]:
        own = entry.get("own", entry["weight"])
        return {**entry, "weight": own + (entry["weight"] - own) / 10}

    entries = sorted((counted(entry) for entry in found.colors.values()), key=lambda e: -e["weight"])
    groups: list[dict[str, Any]] = []
    for entry in entries:
        home = next((g for g in groups if colors.delta_e(g["hex"], entry["hex"]) < 2), None)
        if home is None:
            groups.append({**entry, "where": set(entry["where"]), "names": list(entry["names"]),
                           "details": list(entry["details"])})
            continue
        home["weight"] += entry["weight"]
        home["own"] += entry.get("own", 0.0)
        home["where"] |= entry["where"]
        home["names"] += [n for n in entry["names"] if n not in home["names"]][:3]
        home["details"] += entry["details"][:2]
        home["pantone"] = home["pantone"] or entry["pantone"]
        home["cmyk"] = home["cmyk"] or entry["cmyk"]
    total = sum(g["weight"] for g in groups) or 1
    out = []
    for g in groups[:MAX_COLORS]:
        out.append({"hex": g["hex"], "share": round(100 * g["weight"] / total, 1), "where": sorted(g["where"]),
                    "names": g["names"][:4], "detail": "; ".join(g["details"][:2])[:200], "pantone": g["pantone"],
                    "cmyk": g["cmyk"],
                    # Only from a framework's sheet, or one of Bootstrap's own colours: no colour of the brand.
                    "framework": g.get("own", g["weight"]) <= 0 or g["hex"] in FRAMEWORK_COLORS})
    return out


def order_by_rules(items: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    """Roles without an AI: neutrals by lightness and colourfulness, the heaviest colourful one leads, the next
    clearly different ones become accent and second colour; tiny shares and near repeats are left out."""
    out = []
    taken: list[str] = []
    primary = accent = False
    for item in items:
        _, saturation, lightness = colors.hsl(item["hex"])
        neutral = saturation < 12 or lightness >= 90 or lightness < 8
        near = any(colors.delta_e(item["hex"], other) < 6 for other in taken)
        framework = bool(item.get("framework"))
        keep = not framework and not near and (item["share"] >= 1.0 or neutral is False and item["share"] >= 0.5)
        if framework:
            role = "neutral" if neutral else "secondary"
        elif neutral:
            role = "neutral"
        elif not primary:
            role, primary = "primary", True
        elif not accent:
            role, accent = "accent", True
        else:
            role = "secondary"
        if keep:
            taken.append(item["hex"])
        name = item["names"][0] if item["names"] else describe(item["hex"], language)
        out.append({**item, "role": role, "name": name[:60], "keep": keep, "reason": ""})
    return out


def order_with_ai(items: list[dict[str, Any]], answer: Any, language: str) -> list[dict[str, Any]]:
    """What the AI said, laid over the measured values: only hex values it got count, roles from the list."""
    by_hex = {item["hex"]: item for item in items}
    out: dict[str, dict[str, Any]] = {}
    for entry in (answer.get("colors") if isinstance(answer, dict) else None) or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("hex"), str):
            continue
        value = entry["hex"].strip().upper()
        if value not in by_hex or value in out:
            continue  # not measured: a model may not bring a colour of its own
        role = entry.get("role") if entry.get("role") in ("primary", "secondary", "accent", "neutral") else "secondary"
        name = " ".join(str(entry.get("name") or "").split())[:60] or describe(value, language)
        reason = " ".join(str(entry.get("reason") or "").split())[:200]
        out[value] = {**by_hex[value], "role": role, "name": name, "keep": entry.get("keep") is not False,
                      "reason": reason}
    rest = order_by_rules([i for i in items if i["hex"] not in out], language)
    for item in rest:
        item["keep"] = False
    # A framework's colour stays out unless a person ticks it, whatever the model thought.
    for item in out.values():
        if item.get("framework"):
            item["keep"] = False
    return [*out.values(), *rest]


def fonts_of(found: Found, answer: Any = None) -> list[dict[str, Any]]:
    uses: dict[str, tuple[str, bool]] = {}
    for entry in (answer.get("fonts") if isinstance(answer, dict) else None) or []:
        if isinstance(entry, dict) and isinstance(entry.get("family"), str):
            use = entry.get("use") if entry.get("use") in ("headings", "body", "other") else "other"
            uses[entry["family"].casefold()] = (use, entry.get("keep") is not False)
    rows = sorted(found.fonts.values(), key=lambda e: -e["weight"])[:12]
    out = []
    for index, row in enumerate(rows):
        use, keep = uses.get(row["family"].casefold(), ("headings" if index == 0 else "body" if index == 1 else "other",
                                                        index < 2))
        out.append({"family": row["family"], "where": sorted(row["where"]), "license": row["license"],
                    "detail": row["detail"], "use": use, "keep": keep, "files": list(row.get("files") or [])})
    return out
