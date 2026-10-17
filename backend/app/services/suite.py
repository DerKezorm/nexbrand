"""nexbrand hung on the directory service: connecting, keeping the directory in step, running on its own again.

In short:

* **Connecting** (the operator, here): the address of the directory service and a one-time code made there. nexbrand
sends the code with its own address and gets a client for signing in through the directory service and a token to fetch
the directory. Then the operator matches every account here to a person there (or a new one), every client to a client
  there (or a new one), and the local teams go along. Only then nexbrand counts as connected: from now on people sign in
  through the directory service.
* **Keeping in step**: nexbrand fetches the directory once a minute and whenever the directory service says something
changed (``POST /api/suite/event``, signed with the token). Accounts follow their person (their link at the directory
  service's entry of the provider list, ``oidc_links``; ``suite_person`` says the same),
  teams follow theirs, and each client follows its client there (``external_id`` of its group of rights): name,
  sector, contact, colour and who may see it. A client the directory service brought comes without a design set; it gets
  one here. A blocked person is signed out at once.
* **What is kept there** cannot be changed here: accounts, teams, clients and who may see them, sign-in, mail.
* **The way back**: the operator disconnects here (the directory service forgets the app), or the directory service
disconnects the app, or, with the directory service out of reach, an emergency code does it. nexbrand keeps everything
it got and runs on its own again: the operator's own sign-in with password stays throughout (the emergency account).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .. import __version__
from ..models import (
    MEMBER,
    OPERATOR,
    SIGN_IN_OIDC,
    SIGN_IN_PASSWORD,
    SPACE_ROLES,
    TEAM_ADMIN,
    TEAM_LOCAL,
    Account,
    AuthSession,
    Client,
    Membership,
    Space,
    Team,
    TeamGrant,
    TeamMember,
    new_device_key,
    utcnow,
)
from ..security import decrypt_secret, encrypt_secret, end_all_sessions
from ..vendor.nexoidc import Link, coupling
from . import logs, names, oidc_store, settings_service

logger = logging.getLogger("nexbrand.suite")

KIND = "nexbrand"
#: What nexbrand takes from the directory service. Links between the apps come later; until then they are not claimed.
CAPABILITIES = ["people", "teams", "clients", "mail"]
#: The colours the directory service takes for a client (its palette, the clients' palette here too); a colour from
#: before, outside it, is left out and the directory service chooses.
SUITE_COLORS = ("#f472b6", "#38a9c4", "#fbbf24", "#4ade80", "#ff8a70", "#60a5fa", "#a78bfa", "#a1a1aa")
TIMEOUT = 10.0
#: A notice older than this is refused (against a notice caught and sent again later).
NOTICE_SECONDS = 300
TOKEN_CONTEXT = "suite-token"
SECRET_CONTEXT = "oidc-client-secret"
SMTP_KEYS = ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_password_enc", "smtp_from")
#: The name on the sign-in button while coupled.
SUITE_LABEL = "nexsuite"

_sync_lock = threading.RLock()
#: Saving the choices of a connection under way and finishing it do not cross.
_connect_lock = threading.RLock()
#: What the directory service answers to a pairing; anything else came from something that is not the directory service.
PAIR_CODES = frozenset({"pair_code_invalid", "too_many_attempts", "invalid_url", "unknown_app", "suite_unreachable",
                        # An older connection of this address that still holds, or that the directory service cannot ask
                        # about.
                        "app_still_connected", "app_not_reachable"})
#: Set by the tests: a notice fetches the directory before it answers.
INLINE = False


class SuiteError(Exception):
    def __init__(self, code: str, text: str, status: int = 502) -> None:
        super().__init__(text)
        self.code, self.text, self.status = code, text, status


# --- State ------------------------------------------------------------------------------------------------------------


def state(db: Session) -> str:
    """``""`` (on its own), ``connecting`` or ``connected``."""
    return str(settings_service.get(db, "suite_state") or "")


def connected(db: Session) -> bool:
    return state(db) == "connected"


def _token(db: Session) -> str:
    stored = str(settings_service.get(db, "suite_token_enc") or "")
    return decrypt_secret(stored, TOKEN_CONTEXT) if stored else ""


def operators_from_suite(db: Session) -> list[Account]:
    """The operators here whose role came from the directory service only: they were none before connecting, or were
    made while connected. Never the emergency account. A connection from before the roles were kept
    names nobody: what they were is not known."""
    saved = settings_service.get(db, "suite_saved") or {}
    roles = saved.get("roles") if isinstance(saved, dict) else None
    if not isinstance(roles, dict) or not connected(db):
        return []
    keeper = int(settings_service.get(db, "suite_emergency_account") or 0)
    return [row for row in db.scalars(select(Account).where(Account.role == OPERATOR).order_by(Account.name))
            if row.id != keeper and roles.get(str(row.id)) != OPERATOR]


def operators_unknown(db: Session) -> list[Account]:
    """For a connection from before the roles were kept: the operators here besides the emergency account. Nobody
    knows whether they were operators before, so they stay operators after a disconnect; the dialog names them."""
    saved = settings_service.get(db, "suite_saved") or {}
    if not connected(db) or (isinstance(saved, dict) and isinstance(saved.get("roles"), dict)):
        return []
    keeper = int(settings_service.get(db, "suite_emergency_account") or 0)
    return [row for row in db.scalars(select(Account).where(Account.role == OPERATOR).order_by(Account.name))
            if row.id != keeper]


def view(db: Session) -> dict[str, Any]:
    return {
        "state": state(db),
        "url": str(settings_service.get(db, "suite_url") or ""),
        "last_sync": settings_service.get(db, "suite_last_sync") or None,
        "problem": str(settings_service.get(db, "suite_problem") or ""),
        "emergency_codes": len(settings_service.get(db, "suite_emergency") or []),
        "mail": bool(settings_service.get(db, "suite_mail")),
    }


def refuse_if_managed(db: Session) -> None:
    """For the routes that change what the directory service keeps (accounts, teams, rights, sign-in)."""
    if connected(db):
        from ..errors import error

        raise error("managed_by_suite", "This is kept in nexsuite now.", 409)


def refuse_unless_keeper(db: Session, account: Account, code: str = "disconnect_in_suite",
                         text: str = "Disconnect in nexsuite, or sign in with the emergency account.") -> None:
    """Disconnecting from the app's side is for the emergency account (its password is checked here). Whoever comes
    through the directory service disconnects in the directory service, where the own password is checked; here nobody
    would ask for it. The same for carrying a backup away or deleting one: the archive holds the emergency account's
    password hash and second factor with the key to open it, a way to that account for whoever was never asked for a
    password."""
    if connected(db) and account.id != int(settings_service.get(db, "suite_emergency_account") or 0):
        from ..errors import error

        raise error(code, text, 403)


def dropped(db: Session, space: Space | None) -> bool:
    """A client the directory service gave nexbrand once and no longer does, while connected."""
    return space is not None and bool(space.external_id) and space.suite_dropped_at is not None and connected(db)


def refuse_if_space_managed(db: Session, space_id: int, account: Account | None = None) -> None:
    """The rights of a space the directory service gives this app are kept there. With ``account``: a space it may not
    even read answers as if there were none (404), not "kept in the directory service"."""
    from . import rights

    space = db.get(Space, space_id)
    if account is not None and space is not None and not rights.at_least(rights.role_in(db, account, space.id),
                                                                         rights.READ):
        from ..errors import error

        raise error("not_found", "Not found.", 404)
    if space is not None and space.external_id and connected(db):
        from ..errors import error

        raise error("managed_by_suite", "This is kept in nexsuite now.", 409)


# --- Talking to the directory service ---------------------------------------------------------------------------------


def request(method: str, url: str, *, token: str = "", body: Any = None) -> Any:
    """One call to the directory service's app API; replaced in the tests. Errors as ``SuiteError``."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            answer = client.request(method, url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise SuiteError("suite_unreachable", "nexsuite cannot be reached.") from exc
    if answer.status_code == 401:
        try:
            code = str(answer.json()["detail"]["code"])
        except (ValueError, KeyError, TypeError):
            code = ""
        if code == "app_unknown":
            raise SuiteError("suite_refused", "nexsuite does not know this app any more.", 409)
        # Some other 401 (a proxy asking for a sign-in, ...): not a reason to cut the connection for good.
        raise SuiteError("suite_failed", "nexsuite refused.", 409)
    if answer.status_code >= 400:
        try:
            code = str(answer.json()["detail"]["code"])
        except (ValueError, KeyError, TypeError):
            code = "suite_failed"
        raise SuiteError(code, "nexsuite refused.", 409 if answer.status_code < 500 else 502)
    if answer.status_code == 204 or not answer.content:
        return None
    try:
        return answer.json()
    except ValueError as exc:
        raise SuiteError("suite_failed", "nexsuite answered with something unreadable.") from exc


def picture(url: str, token: str) -> bytes:
    """A profile picture from the directory service; replaced in the tests. Errors as ``SuiteError``."""
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            answer = client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise SuiteError("suite_unreachable", "nexsuite cannot be reached.") from exc
    if answer.status_code != 200:
        raise SuiteError("suite_failed", "nexsuite refused.", 409)
    return answer.content


def _take_picture(db: Session, row: Account, pid: str, stamp: Any, token: str) -> None:
    """The profile picture is kept in the directory service: fetched once per change, gone when it is gone there."""
    from . import avatars

    if not stamp:
        if row.avatar is not None:
            row.avatar, row.avatar_at = None, None
        return
    wanted = _moment(stamp)
    if row.avatar is not None and row.avatar_at == wanted:
        return
    try:
        # Drawn anew like any upload: nothing of the file that came survives but its pixels.
        row.avatar = avatars.make(picture(_api(db, f"/avatars/{pid}"), token))
        row.avatar_at = wanted
    except (SuiteError, avatars.AvatarError) as exc:
        logger.info("Profile picture not taken (%s); tried again with the next sync name=%s",
                    getattr(exc, "code", type(exc).__name__), row.name)


def _api(db: Session, path: str) -> str:
    return str(settings_service.get(db, "suite_url")).rstrip("/") + "/api/connect/v1" + path


def clean_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not re.match(r"^https?://[^/\s?#@]+(/[^\s?#]*)?$", url):
        raise SuiteError("invalid_url", "Type the address of nexsuite, starting with http:// or https://.", 422)
    return url


# --- Connecting -------------------------------------------------------------------------------------------------------


@dataclass
class Proposal:
    people: list[dict[str, Any]]
    accounts: list[dict[str, Any]]
    clients: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    #: The teams here and the teams in the directory service to match them to (by name), so none is brought twice.
    teams: list[dict[str, Any]] = field(default_factory=list)
    team_candidates: list[dict[str, Any]] = field(default_factory=list)
    #: The choices kept from before (``keep_choices``), or None.
    chosen: dict[str, Any] | None = None
    #: How many people, teams and clients an earlier try made in the directory service already: they stay there on
    #: giving up.
    made: int = 0
    #: A /finish went out whose answer did not come: its choices hold, others are refused (``connection_sent``).
    sent: bool = False


def _fold(text: str) -> str:
    return " ".join(text.split()).casefold()


def start(db: Session, url: str, code: str, redirect_uri: str, own_url: str) -> Proposal:
    """Pairs with the code and fetches what to match. Nothing changes for the people here yet."""
    if connected(db):
        raise SuiteError("already_connected", "nexbrand is already connected.", 409)
    if state(db) == "connecting":
        # A second pairing would leave the first, half app in the directory service for good: resume it or give it up.
        raise SuiteError("connecting_already", "A connection is under way: resume it or give it up.", 409)
    base = clean_url(url)
    code = code.strip()
    if not 4 <= len(code) <= 40:
        # The directory service's own rule, checked here: its refusal of the form would read as "not the directory
        # service".
        raise SuiteError("pair_code_invalid", "This code is not valid. Create a new one in nexsuite.", 409)
    try:
        made = request("POST", base + "/api/connect/v1/pair", body={
            "code": code, "url": own_url, "kind": KIND, "name": "nexbrand", "version": __version__,
            "capabilities": CAPABILITIES, "redirect_uri": redirect_uri,
        })
    except SuiteError as exc:
        # Another app at that address (its own refusal would read like one of nexbrand's) or the directory service under
        # a path it does not have: say that the address is wrong.
        if exc.code in PAIR_CODES:
            raise
        raise _not_suite() from exc
    if not isinstance(made, dict) or not all(made.get(key) for key in ("token", "client_id", "client_secret",
                                                                         "issuer")):
        raise _not_suite()
    settings_service.save(db, {
        "suite_url": base,
        "suite_state": "connecting",
        "suite_token_enc": encrypt_secret(str(made["token"]), TOKEN_CONTEXT),
        "suite_pending": {"client_id": made["client_id"], "issuer": made["issuer"],
                          "secret_enc": encrypt_secret(str(made["client_secret"]), SECRET_CONTEXT)},
    })
    logger.info("Paired with nexsuite at %s", base)
    return proposal(db)


def _not_suite() -> SuiteError:
    return SuiteError("not_suite", "No nexsuite answers at this address. Use the address nexsuite opens at, without "
                                   "a path after it.", 409)


def proposal(db: Session) -> Proposal:
    if state(db) != "connecting":
        raise SuiteError("not_connecting", "Start with the address and the code.", 409)
    seen = request("GET", _api(db, "/directory"), token=_token(db))
    people = [p for p in seen["people"] if not p["blocked"]]
    by_mail = {_fold(p["email"]): p["id"] for p in people if p["email"]}
    by_name = {_fold(p["name"]): p["id"] for p in people}
    by_id = {str(p["id"]): p["id"] for p in people}
    everybody = {str(p["id"]) for p in seen["people"]}
    # The person an account had in this very directory service before a disconnect: not one from another directory
    # service, whose ids mean other people.
    same_suite = str(settings_service.get(db, "suite_former_url") or "") == str(settings_service.get(db, "suite_url"))
    operator = operator_id(db)
    # Every suggestion at most once: a second account with the same address or name is suggested as new, never as
    # the same person. The operator's own account goes first, then those the directory service once
    # brought, so their own person is theirs and not taken by a name alike.
    rows = sorted(db.scalars(select(Account)),
                  key=lambda row: (row.id != operator, not (same_suite and row.suite_person), row.id))
    taken: set[str] = set()
    accounts_out = []
    for row in rows:
        former = row.suite_person if same_suite else ""
        blocked = row.blocked_at is not None and row.id != operator
        guess = by_id.get(former) if former else None
        if guess is None and not blocked:
            guess = by_mail.get(_fold(row.email)) if row.email else None
            guess = guess or by_name.get(_fold(row.name))
        if guess in taken:
            guess = None
        if guess:
            taken.add(guess)
        # Blocked here (left out last time, blocked or deleted in the directory service): it stays blocked unless the
        # operator chooses otherwise, never let in again on a default.
        suggest = guess or ("skip" if blocked else "new")
        accounts_out.append({"id": row.id, "name": row.name, "display_name": row.display_name, "email": row.email,
                             "role": row.role, "suggest": suggest, "blocked": blocked,
                             "from_suite": bool(former), "gone": bool(former) and former not in everybody})
    accounts_out.sort(key=lambda entry: entry["id"])
    candidates = list(seen.get("clients_candidates") or [])
    clients_out = _suggest([{"id": c.id, "name": c.name, "color": s.color}
                            for c, s in db.execute(select(Client, Space).join(Space, Space.id == Client.space_id)
                                                   .where(Client.deleted_at.is_(None)).order_by(Client.name))],
                           candidates)
    team_candidates = [{"id": str(t["id"]), "name": t["name"], "color": t.get("color", "")}
                       for t in seen.get("teams") or []]
    teams_out = _suggest([{"id": t.id, "name": t.name, "color": t.color}
                          for t in db.scalars(select(Team).where(Team.source == TEAM_LOCAL).order_by(Team.id))],
                         team_candidates)
    pending = settings_service.get(db, "suite_pending") or {}
    chosen = pending.get("chosen") or None
    sent = pending.get("sent") or {}
    if "chosen" in sent:
        # /finish went out: the choices that went with it, as they were, with their targets by name (the directory
        # service offers no client once it has the connection). Accounts, clients and teams that came here since are not
        # among them.
        picked, named = sent["chosen"], sent.get("names") or {}
        accounts_out = [entry for entry in accounts_out if str(entry["id"]) in picked["accounts"]]
        clients_out = [entry for entry in clients_out if str(entry["id"]) in picked["clients"]]
        teams_out = [entry for entry in teams_out if str(entry["id"]) in picked["teams"]]
        listed = {str(person["id"]) for person in people}
        people = people + [person for person in named.get("people") or [] if person["id"] not in listed]
        candidates = list(named.get("clients") or [])
        listed_teams = {team["id"] for team in team_candidates}
        team_candidates = team_candidates + [team for team in named.get("teams") or []
                                             if team["id"] not in listed_teams]
        chosen = {**picked, "step": 3}
    return Proposal(people=people, accounts=accounts_out, clients=clients_out, candidates=candidates,
                    teams=teams_out, team_candidates=team_candidates, chosen=chosen,
                    made=len(pending.get("made") or {}), sent=bool(sent))


def _as_sent(accounts_map: dict[int, str], clients_map: dict[str, str], teams_map: dict[int, str]) -> dict[str, Any]:
    """The operator's choices as kept with a /finish that went out, to show them again after a reload."""
    return {"accounts": {str(k): v for k, v in accounts_map.items()},
            "clients": {str(k): v for k, v in clients_map.items()}, "teams": {str(k): v for k, v in teams_map.items()}}


def _sent_already() -> SuiteError:
    return SuiteError("connection_sent", "The connection was sent to nexsuite already; its choices apply. Cancel and "
                                         "connect again for other choices.", 409)


def keep_choices(db: Session, chosen: dict[str, Any]) -> None:
    """The operator's choices so far and the step, kept with the connection under way: closing the assistant or
    reloading the page resumes there instead of at the suggestions. Checked and written under the lock a finish
    takes, so a late save never brings back what finishing cleared."""
    with _connect_lock:
        db.expire_all()
        if state(db) != "connecting":
            raise SuiteError("not_connecting", "Start with the address and the code.", 409)
        pending = dict(settings_service.get(db, "suite_pending") or {})
        if pending.get("sent"):
            # The choices of the /finish that went out hold; another one would only seem kept.
            raise _sent_already()
        pending["chosen"] = chosen
        settings_service.save(db, {"suite_pending": pending})
        db.commit()


def _suggest(rows: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each row with the candidate of the same name as suggestion, every candidate at most once."""
    by_name = {_fold(c["name"]): str(c["id"]) for c in candidates}
    taken: set[str] = set()
    for row in rows:
        guess = by_name.get(_fold(row["name"]))
        if guess in taken:
            guess = None
        if guess:
            taken.add(guess)
        row["suggest"] = guess or "new"
    return rows


def operator_id(db: Session) -> int:
    """The account connecting (the first operator), whose suggestion comes first."""
    return int(db.scalar(select(Account.id).where(Account.role == OPERATOR).order_by(Account.id)) or 0)


def _no_twice(choices: dict[int, str], what: str) -> None:
    """A person, client or team in the directory service gets at most one counterpart here."""
    chosen = [choice for choice in choices.values() if choice not in ("new", "skip")]
    twice = sorted({choice for choice in chosen if chosen.count(choice) > 1})
    if twice:
        raise SuiteError(f"{what}_twice", f"Each {what} in nexsuite can be chosen once only.", 422)


def finish(db: Session, operator: Account, accounts_map: dict[int, str], clients_map: dict[str, str],
           teams_map: dict[int, str] | None = None) -> list[dict[str, str]]:
    """Applies the operator's choices: ``person id`` | ``new`` | ``skip`` per account, ``client id`` | ``new`` per
    client, ``team id`` | ``new`` per team. Then nexbrand signs in through the directory service and fetches the
    directory."""
    with _connect_lock:
        db.expire_all()
        return _finish(db, operator, accounts_map, clients_map, teams_map)


def _known(choices: dict[Any, str], known: set[str], what: str, also: tuple[str, ...] = ("new",)) -> None:
    """Every choice names something the directory service has: an id it does not know would leave the account blocked
    and bring the person twice with the next connection."""
    for choice in choices.values():
        if choice not in also and str(choice) not in known:
            raise SuiteError(f"{what}_unknown", f"A {what} you chose is not in nexsuite (any more). Look at the "
                                                f"choices again.", 409)


def _finish(db: Session, operator: Account, accounts_map: dict[int, str], clients_map: dict[str, str],
            teams_map: dict[int, str] | None) -> list[dict[str, str]]:
    if state(db) != "connecting":
        raise SuiteError("not_connecting", "Start with the address and the code.", 409)
    teams_map = teams_map or {}
    sent = (settings_service.get(db, "suite_pending") or {}).get("sent")
    if sent:
        # /finish went out before and its answer did not come, or writing it here failed: the directory service may have
        # the connection already and refuse everything else. Only /finish again, with what was matched then. What came
        # with this request does not count: the choices are fixed since (keeping others is refused, the assistant
        # shows these locked), and accounts made or deleted meanwhile change nothing.
        return _confirm(db, _token(db), sent)
    _no_twice(accounts_map, "person")
    _no_twice(clients_map, "client")
    _no_twice(teams_map, "team")
    token = _token(db)
    made_before = dict((settings_service.get(db, "suite_pending") or {}).get("made") or {})
    new_people: list[dict[str, str]] = []

    def remember(key: str, value: dict[str, str]) -> None:
        """What was made in the directory service, kept at once: a retry after a failure uses it instead of making it
        again."""
        made_before[key] = value
        pending = dict(settings_service.get(db, "suite_pending") or {})
        pending["made"] = dict(made_before)
        settings_service.save(db, {"suite_pending": pending})
        db.commit()
    seen = request("GET", _api(db, "/directory"), token=token)
    # Checked before anything is made in the directory service or changed here.
    _known(accounts_map, {str(p["id"]) for p in seen["people"] if not p.get("blocked")}, "person", ("new", "skip"))
    _known(clients_map, {str(c["id"]) for c in seen.get("clients_candidates") or []}, "client")
    _known(teams_map, {str(t["id"]) for t in seen.get("teams") or []}, "team")
    addresses = {str(p["id"]): p.get("email") or "" for p in seen["people"]}
    shown_names = {str(p["id"]): p.get("display_name") or "" for p in seen["people"]}
    accounts_here = {row.id: row for row in db.scalars(select(Account))}
    person_of: dict[int, str] = {}
    for account_id, choice in accounts_map.items():
        row = accounts_here.get(account_id)
        if row is None or choice == "skip":
            continue
        if choice == "new":
            made = made_before.get(f"person:{row.id}")
            if made is None:
                answer = request("POST", _api(db, "/people"), token=token,
                                 body={"name": row.name, "display_name": row.display_name, "email": row.email})
                made = {"id": str(answer["id"]), "password": str(answer.get("password") or "in_suite")}
                remember(f"person:{row.id}", made)
            new_people.append({"name": row.display_name or row.name, "password": made["password"]})
            choice = made["id"]
        else:
            if row.email and not addresses.get(str(choice)):
                # Matched to a person without an address: the one from here goes along instead of getting lost.
                try:
                    request("POST", _api(db, f"/people/{int(choice)}/email"), token=token, body={"email": row.email})
                except SuiteError:
                    logger.info("nexsuite did not take the address name=%s", row.name)
            if row.display_name and not shown_names.get(str(choice)):
                # The same for the display name: the sync after connecting would otherwise take the person's empty
                # one, and the account would lose the name it had here. A refusal (taken, too
                # long) stops nothing.
                try:
                    request("POST", _api(db, f"/people/{int(choice)}/name"), token=token,
                            body={"display_name": row.display_name})
                except SuiteError:
                    logger.info("nexsuite did not take the display name name=%s", row.name)
        person_of[row.id] = str(choice)
    if operator.id not in person_of:
        raise SuiteError("operator_unmatched", "Your own account needs a person in nexsuite.", 422)
    team_of: dict[int, str] = {}
    for team in db.scalars(select(Team).where(Team.source == TEAM_LOCAL)):
        members = [person_of[m] for m in db.scalars(select(TeamMember.account_id).where(TeamMember.team_id == team.id))
                   if m in person_of]
        lead = person_of.get(team.lead_id) if team.lead_id else None
        choice = teams_map.get(team.id, "new")
        if choice == "new":
            made = made_before.get(f"team:{team.id}")
            if made is None:
                made = {"id": str(request("POST", _api(db, "/teams"), token=token, body={
                    "name": team.name, "color": team.color, "members": members, "lead": lead})["id"])}
                remember(f"team:{team.id}", made)
        else:
            # The same team in the directory service: its members here come along, it is not made a second time.
            made = request("POST", _api(db, f"/teams/{int(choice)}/join"), token=token,
                           body={"members": members, "lead": lead})
        team_of[team.id] = str(made["id"])
    # Nothing here changes before the directory service has confirmed the connection (``/finish``): only what was made
    # there is kept on the way (``remember``). A failure at any step, the last one too, leaves the accounts, teams and
    # clients as they were, and giving up leaves nothing half connected.
    space_of: dict[int, str] = {}
    for client_id, choice in clients_map.items():
        client = db.get(Client, client_id)
        space = db.get(Space, client.space_id) if client is not None and client.deleted_at is None else None
        if client is None or space is None:
            continue
        people = [{"id": person_of[m.account_id], "role": m.role}
                  for m in db.scalars(select(Membership).where(Membership.space_id == space.id))
                  if m.account_id in person_of]
        grants = db.scalars(select(TeamGrant).where(TeamGrant.space_id == space.id))
        teams = [{"id": team_of[g.team_id], "role": g.role} for g in grants if g.team_id in team_of]
        if choice == "new":
            made = made_before.get(f"client:{client.id}")
            if made is None:
                body = {"name": client.name[:80], "sector": client.sector[:80], "contact": client.contact[:120],
                        "people": people, "teams": teams}
                if space.color.lower() in SUITE_COLORS:
                    body["color"] = space.color.lower()
                made = {"id": str(request("POST", _api(db, "/clients"), token=token, body=body)["id"])}
                remember(f"client:{client.id}", made)
            space_of[space.id] = made["id"]
        else:
            # Matched: the rights it has here come along, the directory service keeps the higher where it has one.
            request("POST", _api(db, f"/clients/{int(choice)}/tick"), token=token,
                    body={"people": people, "teams": teams})
            space_of[space.id] = str(int(choice))
    # Kept before /finish goes out: the directory service may take it and the answer never come back (a lost answer, or
    # writing here fails afterwards). The next try sends only /finish again and applies this.
    wanted = {str(choice) for choice in (*accounts_map.values(), *clients_map.values(), *teams_map.values())}
    plan = {"operator": operator.id, "people": {str(k): v for k, v in person_of.items()},
            "teams": {str(k): v for k, v in team_of.items()}, "spaces": {str(k): v for k, v in space_of.items()},
            "skip": [k for k, v in accounts_map.items() if v == "skip"], "new_people": new_people,
            "chosen": _as_sent(accounts_map, clients_map, teams_map),
            # The targets by name, for showing the choices after a reload: the directory service offers no client once
            # it has the connection.
            "names": {
                "people": [{"id": str(p["id"]), "name": p.get("name") or "",
                            "display_name": p.get("display_name") or "", "email": p.get("email") or ""}
                           for p in seen["people"] if str(p["id"]) in wanted],
                "clients": [{"id": str(c["id"]), "name": c.get("name") or "", "color": c.get("color") or ""}
                            for c in seen.get("clients_candidates") or [] if str(c["id"]) in wanted],
                "teams": [{"id": str(t["id"]), "name": t.get("name") or "", "color": t.get("color") or ""}
                          for t in seen.get("teams") or [] if str(t["id"]) in wanted]}}
    pending = dict(settings_service.get(db, "suite_pending") or {})
    pending["sent"] = plan
    settings_service.save(db, {"suite_pending": pending})
    return _confirm(db, token, plan)


def _confirm(db: Session, token: str, plan: dict[str, Any]) -> list[dict[str, str]]:
    """Sends ``/finish`` and, once the directory service has the connection, applies what was matched, here in one
    transaction with the settings (``settings_service.save`` commits). The directory service's ``already_connected`` to
    it, asked with this app's own token, says it took an earlier ``/finish`` whose answer got lost: that is the
    confirmation too."""
    person_of = {int(k): str(v) for k, v in plan["people"].items()}
    team_of = {int(k): str(v) for k, v in plan["teams"].items()}
    space_of = {int(k): str(v) for k, v in plan["spaces"].items()}
    try:
        request("POST", _api(db, "/finish"), token=token, body={"people": len(person_of), "clients": len(space_of)})
    except SuiteError as exc:
        if exc.code != "already_connected":
            raise
        logger.info("nexsuite has the connection already; it is finished here now")
    operator_id = int(plan["operator"])
    accounts_here = {row.id: row for row in db.scalars(select(Account))}
    chosen_accounts = (plan.get("chosen") or {}).get("accounts") or {}
    for space_id, external in space_of.items():
        space = db.get(Space, space_id)
        if space is not None:
            space.external_id = external
            space.suite_dropped_at = None
    for account_id, row in accounts_here.items():
        # Which accounts the directory service knows from now on, by its person: the matched and the made ones, linked
        # to it at the directory service's entry below. One left out is not the directory service's; whatever own link
        # it has (authentik) stays with its own provider, set aside while coupled, and it is never renamed for it.
        person = person_of.get(account_id)
        row.suite_person = person or ""
        # Left out, or made here after the choices (between pairing and finishing, or after /finish went out): no
        # person in the directory service, so no way in while connected, and never a sign-in with a password of its own
        # beside the directory service. Never the emergency account.
        if person is None and account_id != operator_id and row.blocked_at is None:
            row.blocked_at = utcnow()
            if str(account_id) not in chosen_accounts:
                logger.info("Account created after the choices blocked, no person in nexsuite name=%s", row.name)
    for team_id, external in team_of.items():
        team = db.get(Team, team_id)
        if team is not None:
            team.source, team.external_id = TEAM_ADMIN, external
    # Confirmed: everything here in one transaction with the settings below (``settings_service.save`` commits).
    # The directory service becomes the provider: the own entries step aside (switched off; the entry ``oidc`` waits as
    # ``oidc-own``), the directory service takes the slug ``oidc`` with ``/api/oidc/callback``, the address it was told
    # when pairing, and each matched or made account is linked to its person.
    pending = settings_service.get(db, "suite_pending") or {}
    values = settings_service.get_all(db)
    joined = coupling.couple(
        oidc_store.couple_store(db),
        issuer=str(pending.get("issuer", "")),
        client_id=str(pending.get("client_id", "")),
        client_secret=decrypt_secret(str(pending.get("secret_enc", "")), SECRET_CONTEXT),
        label=SUITE_LABEL,
        people=[(account_id, person) for account_id, person in person_of.items() if account_id in accounts_here],
        trusts_second_factor=True,
    )
    settings_service.save(db, {
        # What it was before, for the way back; the roles too, so that an operator role only the directory service gave
        # goes with the connection. An account made while connected was none before: a member. The own providers come
        # back through the coupling kept beside it.
        "suite_saved": {**{key: values[key] for key in (*SMTP_KEYS, "password_login")},
                        "roles": {str(row.id): row.role for row in accounts_here.values()}},
        oidc_store.COUPLING: joined.as_dict(),
        "password_login": False,
        "suite_pending": None,
        "suite_state": "connected",
        "suite_emergency_account": operator_id,
    })
    logger.info("Connected to nexsuite: %s accounts, %s clients", len(person_of), len(space_of))
    sync(db)
    return list(plan.get("new_people") or [])


def abort(db: Session) -> bool:
    """Gives up a connection that did not finish; the directory service is asked to forget the app. A finished
    connection is not given up this way: the directory service would keep the app while it ran on its own, without
    anybody's password. Under the lock a finish holds: a give-up from another tab waits for it and then finds the
    connection done. True when /finish had gone out and the directory service could not be told: it may list the app as
    connected still."""
    with _connect_lock:
        db.expire_all()
        if state(db) == "connected":
            raise SuiteError("already_connected", "nexbrand is already connected.", 409)
        kept = False
        if state(db) == "connecting":
            sent = bool((settings_service.get(db, "suite_pending") or {}).get("sent"))
            try:
                request("POST", _api(db, "/leave"), token=_token(db))
            except SuiteError:
                kept = sent
                if kept:
                    logger.warning("nexsuite not told of giving up a connection it may have; it may list the app")
        _forget(db)
        return kept


# --- Keeping in step --------------------------------------------------------------------------------------------------


def _open_mail(token: str, sealed: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(sealed)
    key = hashlib.sha256(b"nexsuite-seal:" + token.encode()).digest()
    return json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], b"nexsuite-mail"))


def _claim_name(db: Session, person: dict[str, Any], present: set[str], keeper: int,
                renamed: list[tuple[str, str]]) -> str:
    """The name for an account the directory service brings: the person's own. An account the directory service knew
    whose person is gone from it (deleted there; it stays here, blocked, with what it did) moves to the next free name,
    so the new person of that name is called as in the directory service and not ``name2``. Never the emergency account
    (its name is its way in), never an account the directory service never had (left out when connecting: it is nobody's
    there)."""
    base = re.sub(r"[^a-z0-9._-]", "", str(person["name"]).lower())[:60] or "person"
    holder = db.scalar(select(Account).where(Account.name == base))
    if (holder is not None and holder.id != keeper and holder.suite_person
            and holder.suite_person not in present):
        old, shown = holder.name, holder.display_name
        holder.name = _free_name(db, base + "2")
        db.flush()
        # Its display name stands for it too where the new person shows the same one.
        incoming = names.from_suite(person.get("display_name"), 80, invisible=True) or base
        _rename_references(db, holder, old, holder.name, shown if shown and shown == incoming else "")
        renamed.append((old, holder.name))
        # from= and to= are no names of people to the log (logs.rename_actor): this line keeps the move as it was.
        logger.info("Name given to a new person from nexsuite; the account of the deleted one moved from=%s to=%s",
                    old, holder.name)
    return _free_name(db, base)


def _rename_references(db: Session, holder: Account, old: str, new: str, shown: str) -> None:
    """Everything stored by name instead of by id that means ``holder`` follows it from ``old`` to ``new``, in the same
    transaction: nothing it did may read like the new person of the old name. ``shown``: its display name, when
    it is the new person's too; it becomes "shown (new)". Texts customers typed on a review page are theirs, never
    touched. The log follows after the commit (``logs.rename_actor``)."""
    from ..models import BrandVersion, Review, ReviewComment, SpaceNotice

    names = {old: new}
    if shown:
        names[shown] = f"{shown} ({new})"[:80]
    db.execute(update(Client).where(Client.updated_by == old).values(updated_by=new))
    for said, becomes in names.items():
        db.execute(update(BrandVersion).where(BrandVersion.author == said).values(author=becomes))
        db.execute(update(BrandVersion).where(BrandVersion.published_by == said).values(published_by=becomes))
        db.execute(update(Review).where(Review.created_by == holder.id, Review.sender == said).values(sender=becomes))
        db.execute(update(ReviewComment).where(ReviewComment.agency.is_(True), ReviewComment.author == said)
                   .values(author=becomes))
    db.execute(update(SpaceNotice).where((SpaceNotice.actor_id == holder.id) | (SpaceNotice.actor == old))
               .values(actor=new))
    db.execute(update(SpaceNotice).where(SpaceNotice.subject == old).values(subject=new))
    # The licence note of a font names who confirmed it ("confirmed by <name> on <day>"), in versions and reviews.
    notes = [(re.compile(r"((?:von|by) )" + re.escape(said) + r"( (?:am|on) )"), becomes)
             for said, becomes in names.items()]

    def follow(data: Any) -> tuple[Any, bool]:
        if not isinstance(data, dict):
            return data, False
        touched = False
        fonts = []
        for font in data.get("fonts") or []:
            if isinstance(font, dict) and isinstance(font.get("license_note"), str):
                text = font["license_note"]
                for pattern, becomes in notes:
                    text = pattern.sub(lambda match, b=becomes: match.group(1) + b + match.group(2), text)
                if text != font["license_note"]:
                    font, touched = {**font, "license_note": text[:300]}, True
            fonts.append(font)
        return ({**data, "fonts": fonts} if touched else data), touched

    for version in db.scalars(select(BrandVersion)):
        data, touched = follow(version.data)
        if touched:
            version.data = data
    for review in db.scalars(select(Review)):
        variants, any_touched = [], False
        for variant in review.variants or []:
            data, touched = follow(variant.get("data") if isinstance(variant, dict) else None)
            variants.append({**variant, "data": data} if touched else variant)
            any_touched = any_touched or touched
        if any_touched:
            review.variants = variants
    owed = settings_service.get(db, "suite_owed") or {}
    if any(item.get("who") == old for item in owed.get("reports") or []):
        settings_service.save(db, {"suite_owed": {**owed, "reports": [
            {**item, "who": new} if item.get("who") == old else item for item in owed["reports"]]}})


def _free_name(db: Session, wanted: str, own_id: int | None = None) -> str:
    base = re.sub(r"[^a-z0-9._-]", "", wanted.lower())[:60] or "person"
    name, n = base, 2
    while True:
        holder = db.scalar(select(Account).where(Account.name == name))
        if holder is None or holder.id == own_id:
            return name
        name, n = f"{base}{n}", n + 1


def sync(db: Session) -> bool:
    """Fetches the directory and makes nexbrand match it. False when the directory service could not be asked."""
    if not connected(db):
        return False
    with _sync_lock:
        # A disconnect waits for a sync and the other way round; disconnected meanwhile, nothing is applied.
        db.expire_all()
        if not connected(db):
            return False
        token = _token(db)
        try:
            seen = request("GET", _api(db, "/directory"), token=token)
        except SuiteError as exc:
            settings_service.save(db, {"suite_problem": exc.code})
            if exc.code == "suite_refused":
                logger.warning("nexsuite no longer knows this app; running on its own")
                disconnect(db, tell=False)
            return False
        _apply(db, seen, token)
        settings_service.save(db, {"suite_last_sync": utcnow().isoformat(), "suite_problem": "",
                                   "suite_revision": int(seen.get("revision") or 0)})
        return True


#: Sign-ins nexbrand had no account for, and when the directory was fetched for them: at most once per
#: ``CATCH_UP_SECONDS`` for the same one, and only so many held at a time.
CATCH_UP_SECONDS = 30
CATCH_UP_MAX = 1000
_catch_up: dict[str, float] = {}
_catch_up_lock = threading.Lock()
#: The clock of the brake; replaced in the tests.
_clock = time.monotonic


def catch_up(subject: str) -> bool:
    """Fetches the directory for a sign-in nexbrand has no account for yet (a person made in the directory service a
    moment ago), with a session of its own, for a worker thread: the sign-in waits, the server does not. False when held
    back or when the directory service could not be asked."""
    now = _clock()
    with _catch_up_lock:
        for key, at in list(_catch_up.items()):
            if now - at >= CATCH_UP_SECONDS:
                del _catch_up[key]
        if subject in _catch_up or len(_catch_up) >= CATCH_UP_MAX:
            return False
        _catch_up[subject] = now
    from ..db import SessionLocal

    with SessionLocal() as db:
        return sync(db)


def _moment(text: Any) -> datetime:
    """A time the directory service sent; now when it cannot be read."""
    try:
        moment = datetime.fromisoformat(str(text))
    except ValueError:
        return utcnow()
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _same_name(row: Account, person: dict[str, Any] | None) -> bool:
    """The account's sign-in name is the person's: no earlier sync changed it, unlike address and display name, which
    an old sync may have copied onto a stranger's account."""
    return person is not None and row.name == str(person.get("name") or "")


def _switched(row: Account) -> bool:
    """An account with a password of its own that signs in through the provider: only a sync switches one so. Its
    subject is a person of the directory service's, never a link of its own, also once the directory service has deleted
    the person."""
    return row.sign_in == SIGN_IN_OIDC and bool(row.password_hash)


def _settle_waiting(db: Session, store: oidc_store.SqlStore, entry: Any, people: dict[str, dict[str, Any]],
                    keeper: int, signed_out: list[int]) -> None:
    """The persons a migration from 0.1.1 left waiting (``oidc_store.coupled_pairs``): settled as 0.1.1's sync did
    (``_settle_subjects``), now that the directory names them. Unmarked accounts claim a subject when not blocked,
    when they carry the person's sign-in name, or (person deleted there) when a sync had switched them to the
    provider; the first by: marked for exactly this person, the sign-in name is the person's, not blocked, smallest
    id. The owner is linked at the directory service's entry; the others lose the subject (never a link at an own entry)
    and are blocked, and what they hold of the person's goes when address and display name are exactly hers."""
    waiting = settings_service.get(db, oidc_store.WAITING)
    if not isinstance(waiting, dict) or not waiting:
        return
    taken = {link.subject for link in store.links_of_provider(entry.id)}
    linked = {link.account_id for link in store.links_of_provider(entry.id)}
    for subject, ids in waiting.items():
        person = people.get(subject)
        group = [row for row in (db.get(Account, int(account_id)) for account_id in ids)
                 if row is not None and row.oidc_subject == subject and row.id not in linked]
        able = [row for row in group if row.suite_person == subject
                or (not row.suite_person and (row.blocked_at is None or _same_name(row, person)
                                              or (person is None and _switched(row))))]
        owner = None
        if able and subject not in taken:
            owner = min(able, key=lambda row: (row.suite_person != subject, not _same_name(row, person),
                                               row.blocked_at is not None, row.id))
            store.add_link(Link(provider_id=entry.id, subject=subject, account_id=owner.id, issuer=entry.issuer))
            owner.suite_person = subject
            taken.add(subject)
            linked.add(owner.id)
        for row in group:
            if row is owner:
                continue
            logger.info("A subject from before the list lost to another account name=%s", row.name)
            row.oidc_subject, row.suite_person = "", ""
            copied = (person is not None and row.email == str(person.get("email") or "")[:255]
                      and row.display_name == names.from_suite(person.get("display_name"), 80, invisible=True))
            if copied:
                row.email, row.display_name = "", ""
            if row.id != keeper and row.blocked_at is None:
                row.blocked_at = utcnow()
                signed_out.append(row.id)
    settings_service.save(db, {oidc_store.WAITING: None}, commit=False)


def _apply(db: Session, seen: dict[str, Any], token: str) -> None:
    keeper = int(settings_service.get(db, "suite_emergency_account") or 0)
    present = {str(person["id"]) for person in seen.get("people", [])}
    account_of: dict[str, int] = {}
    signed_out: list[int] = []
    renamed: list[tuple[str, str]] = []
    store = oidc_store.SqlStore(db)
    entry = oidc_store.coupled_entry(db)
    if entry is None:
        # Connected without the directory service's entry in the provider list cannot happen through the coupling;
        # nothing is matched by guessing then.
        logger.error("Connected to nexsuite, but its sign-in entry is missing; the directory was not applied")
        return
    # Persons a migration from 0.1.1 could not settle without their sign-in name get their account first.
    _settle_waiting(db, store, entry, {str(person["id"]): person for person in seen.get("people", [])}, keeper,
                    signed_out)
    # Which account is which person: its link at the directory service's entry, one identity per account and provider.
    by_subject: dict[str, Account] = {}
    for link in store.links_of_provider(entry.id):
        holder = db.get(Account, link.account_id)
        if holder is not None:
            by_subject[link.subject] = holder
    for person in seen.get("people", []):
        pid = str(person["id"])
        row = by_subject.get(pid)
        if row is None:
            row = Account(name=_claim_name(db, person, present, keeper, renamed), sign_in=SIGN_IN_OIDC,
                          password_hash="", whats_new_seen=__version__)
            db.add(row)
            db.flush()
            store.add_link(Link(provider_id=entry.id, subject=pid, account_id=row.id, issuer=entry.issuer))
        # The directory service knows this account by its person (also one connected before this was kept).
        row.suite_person = pid
        # Names from the directory service follow the rule for names typed here: no control (C1 too) or format
        # characters.
        row.display_name = names.from_suite(person.get("display_name"), 80, invisible=True)
        row.email = str(person.get("email") or "")[:255]
        # The directory service's address, not a provider's: it stays when the link goes with a disconnect.
        row.email_from_provider = False
        if row.id != keeper:
            # Signs in through the directory service (password and second factor are set there); the own password stays
            # kept for a disconnect. Only the emergency account keeps signing in here.
            row.sign_in = SIGN_IN_OIDC
        _take_picture(db, row, pid, person.get("avatar"), token)
        if person.get("signed_out"):
            # Signed out everywhere in the directory service (or a new password there): the sessions here from before
            # end too.
            ended = db.execute(delete(AuthSession).where(AuthSession.account_id == row.id,
                                                         AuthSession.created_at < _moment(person["signed_out"])))
            if ended.rowcount:
                logger.info("Sessions ended as in nexsuite name=%s count=%s", row.name, ended.rowcount)
            moment = str(person["signed_out"])[:64]
            if moment != row.suite_signed_out:
                # And the browsers known before: their device cookies no longer count, as after "sign out
                # everywhere" here. Once per new moment: a sync that brings the same one changes nothing.
                row.suite_signed_out = moment
                row.device_key = new_device_key()
        if row.id != keeper:
            row.role = OPERATOR if person.get("operator") else MEMBER
        blocked = bool(person.get("blocked"))
        if blocked and row.blocked_at is None:
            row.blocked_at = utcnow()
            signed_out.append(row.id)
        elif not blocked and row.blocked_at is not None:
            row.blocked_at = None
        account_of[pid] = row.id
    # People the directory service no longer has can no longer sign in here; the emergency account neither, as when
    # blocked there. Disconnecting lets it in again. One left out when connecting has no link at
    # the directory service's entry: untouched here, its own link (authentik) waits with its own provider.
    for subject, row in by_subject.items():
        if subject not in account_of and row.blocked_at is None:
            row.blocked_at = utcnow()
            signed_out.append(row.id)
    db.flush()
    team_of: dict[str, int] = {}
    existing = {t.external_id: t for t in db.scalars(select(Team).where(Team.source == TEAM_ADMIN))}
    for item in seen.get("teams", []):
        tid = str(item["id"])
        team = existing.pop(tid, None)
        if team is None:
            team = Team(name=names.from_suite(item["name"], 80) or "?", source=TEAM_ADMIN, external_id=tid)
            db.add(team)
            db.flush()
        # A name another team here has gets a number here; the directory service's own stays as it is.
        team.name = names.unique(db, "team", names.from_suite(item["name"], 80) or "?",
                                 db.scalars(select(Team.name).where(Team.id != team.id)), 80, tid, team.name)
        team.color = str(item.get("color") or team.color)[:16]
        wanted = {account_of[m] for m in item.get("members", []) if m in account_of}
        current = set(db.scalars(select(TeamMember.account_id).where(TeamMember.team_id == team.id)))
        for member in wanted - current:
            db.add(TeamMember(team_id=team.id, account_id=member))
        for member in current - wanted:
            db.execute(delete(TeamMember).where(TeamMember.team_id == team.id, TeamMember.account_id == member))
        team.lead_id = account_of.get(str(item.get("lead"))) if item.get("lead") else None
        team_of[tid] = team.id
    for gone in existing.values():
        db.delete(gone)
    db.flush()
    _apply_clients(db, seen, account_of, team_of)
    sealed = seen.get("mail")
    if sealed:
        mail = _open_mail(token, sealed)
        settings_service.save(db, {
            "smtp_host": str(mail["host"]), "smtp_port": int(mail["port"]), "smtp_security": str(mail["security"]),
            "smtp_user": str(mail["user"]), "smtp_from": str(mail["from"]),
            "smtp_password_enc": encrypt_secret(str(mail["password"])) if mail.get("password") else "",
            "suite_mail": True,
        })
    else:
        # The directory service has no mail server: then neither has the app (the own one is kept for a disconnect). The
        # mail server is the directory service's to set either way, never half here, half there.
        settings_service.save(db, {"smtp_host": "", "smtp_user": "", "smtp_password_enc": "", "smtp_from": "",
                                   "suite_mail": True})
    settings_service.save(db, {"suite_emergency": list(seen.get("emergency") or [])})
    db.commit()
    for old, new in renamed:
        logs.rename_actor(old, new)
    for account_id in signed_out:
        end_all_sessions(db, account_id)


def _apply_clients(db: Session, seen: dict[str, Any], account_of: dict[str, int], team_of: dict[str, int]) -> None:
    """Clients by their id in the directory service: name, sector, contact, colour and rights follow. One the directory
    service made comes here without a design set. In the directory service's trash: in this trash too, with its date;
    deleted there for good: here too."""
    from . import brands

    spaces = {s.external_id: s for s in db.scalars(select(Space).where(Space.external_id != ""))}
    ids = [s.id for s in spaces.values()]
    client_of = {c.space_id: c for c in db.scalars(select(Client).where(Client.space_id.in_(ids)))}
    binned = {str(item.get("id")): item for item in seen.get("clients_bin") or []}
    given: set[str] = set()
    for item in seen.get("clients", []):
        sid = str(item["id"])
        given.add(sid)
        space = spaces.get(sid)
        if space is None:
            space = Space(name=names.from_suite(item["name"], 80) or "?", external_id=sid)
            db.add(space)
            db.flush()
            spaces[sid] = space
        client = client_of.get(space.id)
        if client is None:
            client = Client(id=brands.new_id(), space_id=space.id, name=names.from_suite(item["name"], 120) or "?",
                            updated_by="nexsuite")
            db.add(client)
            db.flush()
            client_of[space.id] = client
            logger.info("Client brought by nexsuite id=%s", client.id)
        # A name another client here has (one of its own, one in the trash) gets a number here.
        client.name = names.unique(db, "client", names.from_suite(item["name"], 120) or client.name,
                                   db.scalars(select(Client.name).where(Client.id != client.id)), 120, client.id,
                                   client.name)
        client.sector = names.from_suite(item.get("sector"), 120)
        client.contact = names.from_suite(item.get("contact"), 255)
        space.name = client.name[:80]
        space.color = str(item.get("color") or space.color)[:16]
        if client.deleted_at is not None and sid not in binned:
            client.deleted_at = None
        space.suite_dropped_at = None
        _set_grants(db, space.id,
                    {account_of[g["id"]]: g["role"] for g in item.get("people", []) if g["id"] in account_of},
                    {team_of[g["id"]]: g["role"] for g in item.get("teams", []) if g["id"] in team_of})
    # Deleted in the directory service: into this trash too, with the directory service's date, so both empty after the
    # same 30 days. A restore there brings it back above.
    for sid, item in binned.items():
        space = spaces.get(sid)
        client = client_of.get(space.id) if space is not None else None
        if client is not None and client.deleted_at is None:
            client.deleted_at = _moment(item.get("deleted_at"))
    # A client the directory service no longer lists and has not binned: nobody but the operator sees it any more,
    # marked "no longer in the directory service", and the operator may put it into the trash here. One in the directory
    # service's bin is still the directory service's: it comes back or goes for good from there, never by the clock or
    # the trash here.
    for sid, space in spaces.items():
        if sid in binned:
            space.suite_dropped_at = None
        if sid not in given and sid not in binned:
            _set_grants(db, space.id, {}, {})
            if space.suite_dropped_at is None:
                space.suite_dropped_at = utcnow()
                logger.info("Client no longer given by nexsuite space=%s", space.id)
    # Deleted for good there: here too, with its versions (their files go with the next clean-up).
    for sid in seen.get("clients_gone") or []:
        space = spaces.get(str(sid))
        if space is not None:
            client = client_of.get(space.id)
            logger.info("Client deleted for good in nexsuite, here too id=%s", client.id if client else "-")
            if client is not None:
                db.delete(client)
            db.delete(space)


def _set_grants(db: Session, space_id: int, people: dict[int, str], teams: dict[int, str]) -> None:
    people = {k: v for k, v in people.items() if v in SPACE_ROLES}
    teams = {k: v for k, v in teams.items() if v in SPACE_ROLES}
    current = {m.account_id: m for m in db.scalars(select(Membership).where(Membership.space_id == space_id))}
    for account_id, role in people.items():
        if account_id in current:
            current.pop(account_id).role = role
        else:
            db.add(Membership(space_id=space_id, account_id=account_id, role=role))
    for row in current.values():
        db.delete(row)
    grants = {g.team_id: g for g in db.scalars(select(TeamGrant).where(TeamGrant.space_id == space_id))}
    for team_id, role in teams.items():
        if team_id in grants:
            grants.pop(team_id).role = role
        else:
            db.add(TeamGrant(space_id=space_id, team_id=team_id, role=role))
    for row in grants.values():
        db.delete(row)


#: Signatures of the notices taken in the last ``NOTICE_SECONDS``, with the moment they run out: the same notice
#: twice is refused.
_notices_seen: dict[str, float] = {}
_notices_lock = threading.Lock()


def check_notice(db: Session, stamp: str, signature: str, body: bytes) -> dict[str, Any] | None:
    """A notice from the directory service, when it carries the right signature, is fresh (neither older nor further
    ahead than ``NOTICE_SECONDS``) and was not taken before; None otherwise."""
    if not connected(db) or not stamp.isascii() or not stamp.isdigit():
        return None
    now = time.time()
    if abs(now - int(stamp)) > NOTICE_SECONDS:
        return None
    expected = hmac.new(_token(db).encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    # Compared as bytes: a signature with characters beyond ASCII is simply wrong, not a failure of the server.
    if not hmac.compare_digest(expected.encode(), signature.encode("utf-8", "replace")):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    with _notices_lock:
        for seen, until in list(_notices_seen.items()):
            if until < now:
                del _notices_seen[seen]
        if expected in _notices_seen:
            return None
        _notices_seen[expected] = int(stamp) + NOTICE_SECONDS
    return data


# --- The way back -----------------------------------------------------------------------------------------------------


def _forget(db: Session) -> None:
    settings_service.save(db, {"suite_state": "", "suite_url": "", "suite_token_enc": "", "suite_pending": None,
                               "suite_emergency": [], "suite_mail": False, "suite_problem": "",
                               "suite_last_sync": None})


def disconnect(db: Session, *, tell: bool = True) -> tuple[list[str], list[str], list[str]]:
    """Runs on its own again with everything it got. Returns the names of accounts without a password (they need
    one from the operator to sign in), of those blocked (in the directory service, or left out): they stay blocked until
    the operator unblocks them here, and of those whose operator role came from the directory service only and is gone
    now. Never while a sync runs."""
    with _sync_lock:
        return _disconnect(db, tell=tell)


def _disconnect(db: Session, *, tell: bool) -> tuple[list[str], list[str], list[str]]:
    if tell and connected(db):
        try:
            request("POST", _api(db, "/leave"), token=_token(db))
        except SuiteError as exc:
            # The directory service has forgotten the app already: nothing to tell. Out of reach: the plain way would
            # leave it holding an app that runs on its own, and make the emergency codes pointless.
            if exc.code != "suite_refused":
                raise SuiteError("suite_unreachable_disconnect",
                                 "nexsuite does not answer. Disconnect with an emergency code, or try again when it is "
                                 "back.", 409) from exc
    saved = settings_service.get(db, "suite_saved") or {}
    # Before the sign-in goes back: an operator role only the directory service gave ends with the connection.
    back = []
    for row in operators_from_suite(db):
        row.role = MEMBER
        back.append(row.name)
        logger.warning("Operator role from nexsuite ended name=%s", row.name)
    restore = {"password_login": saved.get("password_login", True) if isinstance(saved, dict) else True}
    if settings_service.get(db, "suite_mail"):
        restore.update({key: saved[key] for key in SMTP_KEYS if key in saved})
    settings_service.save(db, restore, commit=False)
    for team in db.scalars(select(Team).where(Team.source == TEAM_ADMIN)):
        team.source, team.external_id = TEAM_LOCAL, ""
    for space in db.scalars(select(Space).where(Space.external_id != "")):
        space.external_id = ""
        space.suite_dropped_at = None
    keeper = db.get(Account, int(settings_service.get(db, "suite_emergency_account") or 0))
    if keeper is not None and keeper.blocked_at is not None:
        # Blocked because the directory service blocked or deleted the person: with the directory service gone, it is
        # the way in again.
        keeper.blocked_at = None
        logger.warning("Emergency account let in again on disconnecting name=%s", keeper.name)
        db.flush()
    theirs: list[Account] = []
    entry = oidc_store.coupled_entry(db)
    if entry is not None:
        for link in oidc_store.SqlStore(db).links_of_provider(entry.id):
            # Only the accounts the directory service knew sign in here again, with their password. Kept for connecting
            # again to the same directory service: the account is suggested its own person.
            row = db.get(Account, link.account_id)
            if row is None:
                continue
            row.suite_person = link.subject
            if row.password_hash:
                row.sign_in = SIGN_IN_PASSWORD
            theirs.append(row)
    # The directory service's entry goes with its links, and every own entry comes back as it was before connecting: one
    # left out when connecting signs in with its own link (authentik) again.
    store = oidc_store.couple_store(db)
    kept = settings_service.get(db, oidc_store.COUPLING)
    if isinstance(kept, dict) and kept.get("provider_id"):
        coupling.uncouple(store, coupling.Coupling.from_dict(kept))
    elif entry is not None:
        logger.warning("No coupling kept for nexsuite's sign-in entry; it goes, the own entries stay as they are")
        store.delete_provider(entry.id)
    db.flush()
    without = [row.name for row in theirs
               if not row.password_hash and row.blocked_at is None and not oidc_store.has_links(db, row.id)]
    blocked = [row.name for row in
               db.scalars(select(Account).where(Account.blocked_at.is_not(None)).order_by(Account.name))]
    # Persons a migration left waiting get no link any more: their accounts keep what they have here.
    settings_service.save(db, {"suite_former_url": str(settings_service.get(db, "suite_url") or ""),
                               oidc_store.COUPLING: None, oidc_store.WAITING: None}, commit=False)
    db.commit()
    _forget(db)
    logger.warning("Disconnected from nexsuite; running on its own")
    return without, blocked, back


def emergency_ok(db: Session, code: str) -> bool:
    digest = hashlib.sha256(re.sub(r"[^A-Z0-9]", "", code.upper()).encode()).hexdigest()
    return any(hmac.compare_digest(digest, h) for h in settings_service.get(db, "suite_emergency") or [])


def report(db: Session, kind: str, who: str) -> None:
    """Tells the directory service something for its log. Out of reach, the report waits and goes with a later round,
    with the address and key of the moment, also after an emergency disconnect."""
    owed = dict(settings_service.get(db, "suite_owed") or {})
    url = str(settings_service.get(db, "suite_url") or "")
    token = str(settings_service.get(db, "suite_token_enc") or "")
    if not url or not token:
        return
    if owed.get("url") != url or owed.get("token_enc") != token:
        owed = {"url": url, "token_enc": token, "reports": []}
    owed["reports"] = [*owed.get("reports", []), {"kind": kind, "who": who[:80]}][-OWED_MAX:]
    settings_service.save(db, {"suite_owed": owed})
    db.commit()
    deliver(db)


#: Reports kept for the directory service while it is out of reach; the oldest go first when there are more.
OWED_MAX = 50


def deliver(db: Session) -> None:
    """Sends what the directory service still has to hear (each round of the background loop, connected or not)."""
    owed = settings_service.get(db, "suite_owed") or {}
    reports = list(owed.get("reports") or [])
    if not reports:
        return
    token = decrypt_secret(str(owed["token_enc"]), TOKEN_CONTEXT)
    left: list[Any] = []
    for index, item in enumerate(reports):
        try:
            request("POST", str(owed["url"]).rstrip("/") + "/api/connect/v1/report", token=token, body=item)
        except SuiteError as exc:
            if exc.code == "suite_refused":
                break  # The directory service has forgotten the app: nobody left to tell
            left = reports[index:]
            logger.info("nexsuite not told yet about %s (out of reach), tried again later", item.get("kind"))
            break
    settings_service.save(db, {"suite_owed": {**owed, "reports": left} if left else None})
    db.commit()


def run_forever_sync() -> None:
    """One round of the background loop (``main.py`` calls it once a minute)."""
    from ..db import SessionLocal

    with SessionLocal() as db:
        deliver(db)
        if connected(db):
            sync(db)
