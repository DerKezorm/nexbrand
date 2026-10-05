# The nexbrand API

Build pipelines, scripts, [nexdeck](https://github.com/DerKezorm/nexdeck) and AI tools in an editor read a client's
design set from nexbrand: colours, fonts, logos, type scale and rules, as JSON or as code to paste. Two ways in, with
the same tokens and the same rights:

- **`/api/v1`**, plain HTTP for programs.
- **`/api/mcp`**, the Model Context Protocol for an AI assistant in an editor.

Reading changes nothing. A token of the level **draft** may also write a version back, always as a draft; publishing
stays a person's act in nexbrand.

## Switching it on

API tokens are off until the operator switches them on, under **Settings → Server → API**. Then every account makes
its own tokens under **My account → Connections**:

- A token reads what its account may read, never more. A new one sees only the clients chosen for it; every client the
  account may read, later ones too, is chosen on purpose.
- Its level is **read** (the default) or **draft**: a draft token may also propose a version where its account may
  write. The list says which.
- It runs out after 90 days, unless 30, 365 days or never is chosen. The list marks a token a week before it runs
  out.
- It is shown once, right after it was made. nexbrand keeps only a checksum.
- The operator sees every token (never the token itself) and can block one for good.
- A blocked or deleted account has no working token: a blocked one answers like none until the account is let in
  again, a deleted one is gone with it. The same when nexsuite blocks or deletes the person. An account locked for a
  while after wrong passwords keeps its tokens, so nobody switches a program off by guessing. Rights taken away at a
  client are gone for its tokens at once.

Fonts with the licence **internal** never leave through a token: the design set names them, their files are not
handed out. A file that any version of the client keeps as an internal font is left out everywhere else as well: as
an example, as a logo download, as the file of a font another version calls free. It stays so when that version is
deleted; to share the file, upload it again.

## Asking

Every request carries the token in a header:

```
Authorization: Bearer nxb_…
```

A request that carries an `Origin` header is refused (403): the API is for programs, not web pages. The answers are
JSON; code comes as text.

| Answer | Code | Meaning |
|---|---|---|
| 401 | `api_off` | The operator has not switched API tokens on. |
| 401 | `token_invalid` | No such token, or it ran out, was deleted (withdrawn) or blocked by the operator, its account is blocked or deleted, or the operator requires a second factor its account has not set up yet. |
| 403 | `origin_refused` | The request came from a web page. |
| 403 | `level_too_low` | A read token tried to propose a draft. |
| 404 | `not_found` | No such client, version, project or file, or the token may not read it. Both answer the same. |
| 422 | `invalid_input` | A value that is not a colour, a day that is not `YYYY-MM-DD`, a design set of the wrong shape. |
| 429 | `slow_down` | More than 600 requests in a minute with this token; `Retry-After` says when to go on. |

Errors look like `{"detail": {"code": "token_invalid", "message": "No valid API token."}}`.

**The promise.** What is under `/api/v1` stays as it is: new fields may come, nothing is renamed or taken away. A
change that would break a program goes to `/api/v2` beside it.

## Routes

A client is named by its id or its name (`Example Bakery`, as it is written in nexbrand, any case). A version by its
id or its label (`2026`, `1.0`). A project by its id or its name. No two clients have the same name, and no two
projects of one client: nexbrand compares names without capitals, without spaces at the ends, with spaces inside
folded to one, without invisible signs (a zero-width space) and in one Unicode form (NFKC).

The version that holds today is the published one with the latest day that is not after today. A version published
to hold from a later day (`valid_from`) holds from that day on, not before: until then `current_version`, the
standard answer, the code and the audit go by the version before it. With no version before it (a client or project
whose only published version holds from a later day), `current_version` is `null`, and the standard answer, the code
and the audit give that coming version with `current: false`.

### `GET /api/v1/me`

Who the token speaks for: `name`, `display_name`, `level` (`read` or `draft`), `clients` (how many it may read) and
the `version` of nexbrand.

### `GET /api/v1/clients`

The clients the token may read. `?search=` keeps those whose name or sector contains it.

Each: `id`, `name`, `sector`, `current_version` (the label of the version that holds today, or `null`),
`colors` (up to twelve hex values of that version) and `projects` (`id`, `name`).

### `GET /api/v1/clients/{client}`

A client's design set. Without a parameter, the version that holds today.

| Parameter | Meaning |
|---|---|
| `version` | A version by label or id, published or draft. |
| `at` | A day, `YYYY-MM-DD`: the version that held then (`?at=2023-10-04` for "three years ago"). |
| `project` | A project (an app, a product, a campaign of the client) with a design set of its own: its current version, or its newest draft; with `version` or `at`, one of the project's versions. The answer is the project's set as shown: the parts it takes from the client version it stands on, with its own. |

```json
{
  "client": {"id": "m14tCjpkfnvZ", "name": "Example Bakery", "sector": "Bakery"},
  "project": null,
  "version": {"id": "k30G1ZelflqM", "label": "2026", "status": "published", "valid_from": "2026-03-01",
              "origin": "hand", "author": "robin", "note": ""},
  "current": true,
  "design": {"colors": [{"name": "Dawn red", "hex": "#C23B2E", "role": "primary"}], "fonts": [], "logos": [],
             "scale": [], "rules": [], "samples": []},
  "files": {"Hk2…": {"name": "logo.svg", "kind": "svg", "size": 2311, "url": "https://brand.example.com/api/v1/files/Hk2…"}},
  "checks": [{"level": "warn", "code": "white_on", "colors": ["Dawn red"], "hex": ["#FFFFFF", "#E0453A"], "ratio": 4.13}]
}
```

`origin` says where a version came from: `hand`, `collect` (collected from websites, repositories or PDFs), `mcp`
(written back by a token) or `review` (chosen by the client). `checks` are the same hints the app computes: contrast
by WCAG 2.2, logos at 3:1, colour vision deficiencies, nearly identical colours, small body text, font licences,
and what the set's own rules say against it (codes starting with `rule_`, with `rule`, the rule's place in `rules`).
Each has a `level` (`warn` or `bad`), a `code`, the names and hex values it is about, and a `ratio` where one
applies. Nothing to say means an empty list.

### `GET /api/v1/clients/{client}/versions`

Every version, published ones in the order they hold, then drafts; each as `version` above.

### `GET /api/v1/clients/{client}/code`

The design set as code to paste, with `version`, `at` and `project` as above.

| `format` | What comes |
|---|---|
| `css` (default) | CSS variables: every colour with its scale 50 to 950, fonts, and each step of the type scale: its size in `rem` (`--text-h1`), line height (`--text-h1--line-height`) and weight (`--text-h1--font-weight`). |
| `tailwind` | A Tailwind 4 `@theme` block, with the same names (Tailwind reads them as one text size). |
| `scss` | SCSS variables (`$text-h1`, `$text-h1-line-height`, `$text-h1-font-weight`). |
| `json` | Design tokens (W3C draft format): sizes under `text`, line heights under `lineHeight`, weights under `fontWeight`. |

### `POST /api/v1/clients/{client}/audit`

Colour values found in code or on a page, against the design set (or a project's colours with `project`):

```json
{"colors": ["#c23b2f", "#1a1a1a", "rgb(20, 40, 90)"], "project": null}
```

A value may be written as style sheets write it: `#RGB`, `#RRGGBB` (with alpha, which is left out), the same without
`#`, `rgb()`/`rgba()` and `hsl()`/`hsla()` with commas or spaces. Names such as `red` are not read.

Each value comes back with a `verdict`: `same` (ΔE 2000 below 1), `near` (below 8, mostly a slip: `nearest` and
`nearest_hex` say what was meant), `foreign`, or `unreadable`. Up to 500 values per request.

With `css`, a style sheet (up to 500,000 characters), its colours join the list, and every CSS rule that sets both
`color` and `background` (or `background-color`) is checked. `var()` is resolved through the sheet's own custom
properties. The answer gets a `css` part:

```json
{"checked": 12,
 "pairs": [{"selector": ".badge", "fg": "#FFFFFF", "bg": "#E9A23B", "fg_name": "White", "bg_name": "Honey",
            "ratio": 2.16, "verdict": "forbidden", "rule": 3}]}
```

`forbidden` means a rule of the set forbids the pair (`rule` is its place); `low_contrast` means below 4.5:1. Only a
pair inside one CSS rule is seen: a ground inherited from a parent or set by another class is not.

### Projects

A project has versions of its own, like the client. Each stands on a version of the client's and takes each part
(`colors`, `fonts`, `logos`, `scale`, `rules`, `samples`, `dark`) from it, takes it and adds its own (same name
replaces), or has it its own. A draft written back for a project (over the app) keeps only what is its own, with
`"inherit": {"colors": "extend", "logos": "own"}`; a part not named comes from the client. What `get_brand` and the
code export give is always the whole set as the project shows it.

### Dark mode

`dark` in a design set is optional: which of its colours is what in dark mode, each by name: `ground` (the page),
`surface` (cards, panels), `text`, `muted` (quieter text), `primary` (links, buttons), `on_primary` (text on
buttons). The checks hold text, quiet text, links and button text at 4.5:1 to what they stand on (codes starting
with `dark_`), and `dark_missing` names a colour the palette no longer has. The code export carries it as
`--dark-ground: var(--color-…)` (CSS), `--color-dark-…` (Tailwind), `$dark-…` (SCSS) and a `dark` group (JSON).

### Rules

`rules` in a design set are `do` or `dont`, and of a `type`. Only `text` rules are free words; the others point at
parts of the set by name and are checked:

| `type` | Fields | Checked |
|---|---|---|
| `pair` | `fg`, `bg` (colour names), `size`: `text` or `large` | allowed pair below 4.5:1 (or 3:1), a logo showing a forbidden pair, a pair both allowed and forbidden, the audit's `css` |
| `logo` | `logo` (logo id), `grounds` (colour names) | the logo's own ground, its word mark against each allowed ground at 3:1 |
| `font` | `font` (family), `use`: empty, `headings` or a step's use, `min_size` (px) | the type scale's steps of that use |
| `text` | `text`, `topic`: `logo`, `color`, `font`, `image`, `tone` | never |

Every rule may carry `text` as a note. A name the set no longer has is reported as `rule_missing`.

### `POST /api/v1/clients/{client}/drafts`

Only for **draft** tokens, and only where the token's account may write. Proposes a new version as a draft:

```json
{"label": "Redesign 2027", "note": "Warmer red, larger body text.", "based_on": "2026",
 "data": {"colors": [{"name": "Dawn red", "hex": "#B8352A", "role": "primary"}]}}
```

With `based_on`, the parts of the design set that are not sent are taken from that version (logos and fonts with
their files, for instance). The answer is the new `version` (origin `mcp`) with its `checks`. The draft shows up in
nexbrand with the token's name as author; a person publishes it there, or throws it away.

### `GET /api/v1/contrast?fg=…&bg=…`

Two colours, written as for the audit (`#` as `%23`; `000`, `rgb(0 0 0)` and `hsl(…)` work too):
`ratio`, `text` and `large_text` (`AAA`, `AA`, `AA large` or `fail`), `graphics` (`pass` or `fail`), `vision`
(the ratio as people with each colour vision deficiency see it) and, below 4.5:1, `nearest_passing`: the nearest
colour of the same hue that reaches it. Every `ratio` in the API is cut, never rounded up: to two places, from 10:1 to
one (12.36 is 12.3). 4.4992 is 4.49, so a ratio shown at or above a threshold has reached it.

### `GET /api/v1/files/{id}`

A logo, a free font or an example file named in a design set's `files`. A file that any version of the client keeps
as an internal font answers 404.

## MCP

`POST /api/mcp` speaks MCP's Streamable HTTP transport without streams: JSON-RPC 2.0, every request gets its answer
as JSON, a notification gets 202. No session is kept; every request carries the token as above. In the usual MCP
configuration of an editor:

```json
{"mcpServers": {"nexbrand": {"type": "http", "url": "https://brand.example.com/api/mcp",
                             "headers": {"Authorization": "Bearer nxb_…"}}}}
```

| Tool | Level | What it does |
|---|---|---|
| `list_clients` | read | The clients, with their current version, main colours and projects. |
| `get_brand` | read | A client's design set, with `version`, `at` or `project` as in the routes above. |
| `get_code` | read | The design set as CSS, Tailwind, SCSS or tokens. |
| `list_versions` | read | Every version, with the day it holds from. |
| `compare_versions` | read | What changed between two versions: colours (with their distance), fonts, and in `changes` every part (colours, fonts, logos, type scale, rules, examples, dark mode), each field with its value before and after. |
| `check_contrast` | read | Contrast of a text colour on a ground, with grades and the nearest passing colour. |
| `audit` | read | Colour values from code against the design set; with `css`, colour pairs against the rules. |
| `propose_version` | draft | A redesign written back as a draft. A read token does not see this tool. |
