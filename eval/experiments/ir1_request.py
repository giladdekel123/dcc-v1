"""IR-1 stage 1: frozen interpreted requests and the deterministic retrieval plan. No retrieval.

Specification: IR1_PREREGISTRATION.md (sections 5, 6, 9), ir1_frozen58_annotations.yaml and
IR1_CLARIFICATIONS.md (C1, C2). This module reads only the frozen annotation file: no database,
corpus, expected answers or evaluation data. Planning is a pure function of one request.

The plan separates what later stages act on (hard filters, soft clues, pool text, relation and
state intent) from what is kept for audit only (approx, verify, withdrawn, provenance).

Validation is strict about keys, types, enums and blank values. PyYAML keeps the last of any
duplicate mapping keys; that is outside this validation (the frozen file is pinned by SHA-256).
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

import yaml

FROZEN_PATH: Final = Path(__file__).resolve().parent / "ir1_frozen58_annotations.yaml"
FROZEN_SHA256: Final = "5b68dab1e8eff7c2c82aa6e9e07d5686ce47ee7a06c27aae9bd3e706e577f860"
FROZEN_COUNT: Final = 58

# Preregistration section 6 (line 136): fixed now, not tuned, no override.
POOL_SIZE: Final = 50
LIKELY_BOOST: Final = 0.5
CONTEXT_BOOST: Final = 0.1
ANCHOR_COUNT: Final = 3

CLUE_FIELDS: Final = ("doc_type", "discipline", "stage", "originator", "sender", "wbs")
STRENGTHS: Final = ("confirmed", "likely", "context")
LINK_TYPES: Final = ("responds_to", "supersedes", "affects", "generated_from", "clarified_by", "related_to", "any")
TARGET_SIDES: Final = ("from", "to")
REVISION_STATES: Final = ("best_match", "latest", "latest_for_construction", "earliest", "earliest_for_construction")
DOCUMENT_STATES: Final = ("any", "current")
DEFAULT_REVISION_STATE: Final = "best_match"
DEFAULT_DOCUMENT_STATE: Final = "any"

# M1: a confirmed clue becomes the existing filter of the same meaning (keys of app Filters);
# originator and sender both use the organisation filter. WBS is absent: C1 makes it context.
HARD_FILTER_KEY: Final = MappingProxyType({"doc_type": "doc_type", "discipline": "discipline", "stage": "stage",
                                           "originator": "org", "sender": "org"})
BOOST: Final = MappingProxyType({"likely": LIKELY_BOOST, "context": CONTEXT_BOOST})

REQUEST_REQUIRED: Final = frozenset({"id", "raw_text", "text", "clues", "revision_state", "document_state",
                                     "approx", "verify", "withdrawn"})
REQUEST_OPTIONAL: Final = frozenset({"relation", "source_file", "state_source"})
CLUE_KEYS: Final = frozenset({"field", "code", "strength", "source"})
RELATION_KEYS: Final = frozenset({"link_type", "target_side", "anchor_text", "source"})
UNRESOLVED_KEYS: Final = frozenset({"id", "field", "source", "reason"})


class RequestError(ValueError):
    """The frozen file or a request does not match the frozen schema."""


class PlanError(ValueError):
    """A request needs a planning rule the frozen specification does not define."""


@dataclass(frozen=True)
class Clue:
    field: str
    code: str
    strength: str
    source: str


@dataclass(frozen=True)
class Relation:
    link_type: str
    target_side: str
    anchor_text: str
    source: str


@dataclass(frozen=True)
class Unresolved:
    id: str
    field: str
    source: str
    reason: str


@dataclass(frozen=True)
class Request:
    id: str
    raw_text: str
    text: str
    clues: tuple[Clue, ...]
    relation: Relation | None
    revision_state: str
    document_state: str
    approx: tuple[str, ...]
    verify: tuple[str, ...]
    withdrawn: tuple[str, ...]
    source_file: str | None = None
    state_source: tuple[str, ...] = ()
    raw_json: str = ""                 # the request exactly as frozen, canonical JSON, for audit


@dataclass(frozen=True)
class FrozenRequests:
    sha256: str
    requests: tuple[Request, ...]
    unresolved: tuple[Unresolved, ...]


@dataclass(frozen=True)
class HardFilter:
    key: str                           # Filters field: doc_type, discipline, stage or org
    code: str
    clue: Clue


@dataclass(frozen=True)
class SoftClue:
    field: str
    code: str
    frozen_strength: str               # as annotated
    strength: str                      # used for retrieval (C1: wbs is always context)
    boost: float
    source: str
    reclassified: str | None = None    # "C1" when strength differs from frozen_strength


@dataclass(frozen=True)
class Audit:
    """Recorded for the interpretation record. None of these is an active filter, soft clue,
    relation signal, lexical rewrite instruction or state instruction. Under the preregistered
    default-request definition (lines 97-98), a non-empty approx, verify or withdrawn does make
    is_default false, and so affects M0/default detection; that is their only effect."""
    raw_text: str
    text: str
    approx: tuple[str, ...]
    verify: tuple[str, ...]
    withdrawn: tuple[str, ...]
    source_file: str | None
    state_source: tuple[str, ...]
    unresolved: tuple[Unresolved, ...]
    removed_phrases: tuple[str, ...]   # C2 context-source phrases found and removed from text
    pool_text_fallback: bool           # C2.5: removal left nothing, frozen text used


@dataclass(frozen=True)
class Plan:
    request_id: str
    is_default: bool                   # M0: later stages must return the baseline result unchanged
    hard_filters: tuple[HardFilter, ...]
    soft_clues: tuple[SoftClue, ...]
    pool_text: str                     # lexical text for the candidate pool, after C2
    relation: Relation | None          # M3 intent; anchors and links are not resolved here
    revision_state: str                # M4 intent; no revision is selected here
    document_state: str                # M4 intent; nothing is reordered here
    audit: Audit

    def filters(self) -> dict[str, str]:
        """The hard filters as keyword arguments for app.retrieval.base.Filters."""
        return {f.key: f.code for f in self.hard_filters}

    def retrieval_signature(self) -> tuple:
        """Everything later stages may act on, and nothing else. approx, verify and withdrawn enter
        only through is_default (see Audit)."""
        return (self.is_default, self.hard_filters, self.soft_clues, self.pool_text, self.relation,
                self.revision_state, self.document_state)


# ---------------------------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------------------------

def _string(value, where: str) -> str:
    if not isinstance(value, str):
        raise RequestError(f"{where}: expected a string, got {type(value).__name__}")
    return value


def _nonblank(value, where: str) -> str:
    if not _string(value, where).strip():
        raise RequestError(f"{where}: must not be empty or whitespace only")
    return value


def _strings(value, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RequestError(f"{where}: expected a list, got {type(value).__name__}")
    return tuple(_string(v, f"{where}[{i}]") for i, v in enumerate(value))


def _choice(value, allowed: tuple[str, ...], where: str) -> str:
    if _string(value, where) not in allowed:
        raise RequestError(f"{where}: {value!r} is not one of {allowed}")
    return value


def _keys(item, required: frozenset, optional: frozenset, where: str) -> None:
    if not isinstance(item, dict):
        raise RequestError(f"{where}: expected a mapping, got {type(item).__name__}")
    missing, unknown = required - set(item), set(item) - required - optional
    if missing or unknown:
        raise RequestError(f"{where}: missing {sorted(missing)} / unknown {sorted(unknown)} fields")


def _literal(phrase: str, raw_text: str, where: str) -> str:
    if phrase not in raw_text:
        raise RequestError(f"{where}: {phrase!r} is not a literal substring of raw_text")
    return phrase


def parse_request(item) -> Request:
    """One request mapping, validated against the frozen schema (preregistration section 5)."""
    where = f"request {item.get('id', '?') if isinstance(item, dict) else '?'}"
    _keys(item, REQUEST_REQUIRED, REQUEST_OPTIONAL, where)
    raw_text = _nonblank(item["raw_text"], f"{where}.raw_text")
    if not isinstance(item["clues"], list):
        raise RequestError(f"{where}.clues: expected a list")
    clues = []
    for i, c in enumerate(item["clues"]):
        w = f"{where}.clues[{i}]"
        _keys(c, CLUE_KEYS, frozenset(), w)
        clues.append(Clue(field=_choice(c["field"], CLUE_FIELDS, f"{w}.field"),
                          code=_nonblank(c["code"], f"{w}.code"),
                          strength=_choice(c["strength"], STRENGTHS, f"{w}.strength"),
                          source=_literal(_nonblank(c["source"], f"{w}.source"), raw_text, f"{w}.source")))
    relation = None
    if "relation" in item:                                    # omitted when there is none; never null
        r, w = item["relation"], f"{where}.relation"
        if r is None:
            raise RequestError(f"{w}: must be omitted, not null, when there is no relation")
        _keys(r, RELATION_KEYS, frozenset(), w)
        relation = Relation(link_type=_choice(r["link_type"], LINK_TYPES, f"{w}.link_type"),
                            target_side=_choice(r["target_side"], TARGET_SIDES, f"{w}.target_side"),
                            anchor_text=_string(r["anchor_text"], f"{w}.anchor_text"),
                            source=_literal(_nonblank(r["source"], f"{w}.source"), raw_text, f"{w}.source"))
    source_file = item.get("source_file")
    return Request(
        id=_string(item["id"], f"{where}.id"),
        raw_text=raw_text,
        text=_nonblank(item["text"], f"{where}.text"),
        clues=tuple(clues),
        relation=relation,
        revision_state=_choice(item["revision_state"], REVISION_STATES, f"{where}.revision_state"),
        document_state=_choice(item["document_state"], DOCUMENT_STATES, f"{where}.document_state"),
        approx=_strings(item["approx"], f"{where}.approx"),
        verify=_strings(item["verify"], f"{where}.verify"),
        withdrawn=_strings(item["withdrawn"], f"{where}.withdrawn"),
        source_file=None if source_file is None else _string(source_file, f"{where}.source_file"),
        state_source=_strings(item.get("state_source", []), f"{where}.state_source"),
        raw_json=json.dumps(item, ensure_ascii=False, sort_keys=True),
    )


def parse_document(data, sha256: str, expected_count: int | None = FROZEN_COUNT) -> FrozenRequests:
    """The parsed annotation document: `requests` plus `unresolved_vocabulary`."""
    _keys(data, frozenset({"requests", "unresolved_vocabulary"}), frozenset(), "document")
    if not isinstance(data["requests"], list):
        raise RequestError("document.requests: expected a list")
    requests = tuple(parse_request(item) for item in data["requests"])
    ids = [r.id for r in requests]
    if len(set(ids)) != len(ids):
        raise RequestError(f"duplicate request ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    if expected_count is not None and len(requests) != expected_count:
        raise RequestError(f"expected {expected_count} requests, found {len(requests)}")
    if not isinstance(data["unresolved_vocabulary"], list):
        raise RequestError("document.unresolved_vocabulary: expected a list")
    unresolved = []
    for i, u in enumerate(data["unresolved_vocabulary"]):
        w = f"unresolved_vocabulary[{i}]"
        _keys(u, UNRESOLVED_KEYS, frozenset(), w)
        if u["id"] not in ids:
            raise RequestError(f"{w}: unknown request id {u['id']!r}")
        unresolved.append(Unresolved(**{k: _string(u[k], f"{w}.{k}") for k in ("id", "field", "source", "reason")}))
    return FrozenRequests(sha256=sha256, requests=requests, unresolved=tuple(unresolved))


def load_frozen_requests(path: Path = FROZEN_PATH, expected_sha256: str = FROZEN_SHA256) -> FrozenRequests:
    """The frozen requests. The file's SHA-256 is checked before it is parsed."""
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    if sha256 != expected_sha256:
        raise RequestError(f"{path.name}: SHA-256 {sha256} does not match the frozen {expected_sha256}")
    return parse_document(yaml.safe_load(raw), sha256)


# ---------------------------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------------------------

def is_default(request: Request) -> bool:
    """Preregistration lines 97-98: only raw_text and text equal to it, every other field at its
    default. Provenance (source_file, state_source, unresolved_vocabulary) is not a request field."""
    return (request.text == request.raw_text and not request.clues and request.relation is None
            and request.revision_state == DEFAULT_REVISION_STATE
            and request.document_state == DEFAULT_DOCUMENT_STATE
            and not request.approx and not request.verify and not request.withdrawn)


def effective_strength(clue: Clue) -> str:
    """C1: a wbs clue behaves as context for retrieval, whatever its frozen strength."""
    return "context" if clue.field == "wbs" else clue.strength


def _phrase_pattern(phrase: str) -> re.Pattern:
    """C2.2-2.3: the complete phrase, case-insensitive, on whole-word boundaries (not next to a
    word character); internal whitespace matches any run of whitespace."""
    words = phrase.split()
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words) + r"(?!\w)", re.IGNORECASE)


def remove_context_sources(text: str, sources: tuple[str, ...]) -> tuple[str, tuple[str, ...], bool]:
    """C2: (pool text, phrases removed, fell back to text). Occurrences are found in the frozen text
    and removed together, so removing one phrase cannot create or break a match of another.
    Sources that normalise to the same phrase (whitespace collapsed, casefolded) are one source."""
    unique: dict[str, str] = {}
    for s in sources:
        if s.split():
            unique.setdefault(" ".join(s.split()).casefold(), s)
    phrases = tuple(unique.values())
    spans: list[tuple[int, int, str]] = []
    for phrase in phrases:
        spans += [(m.start(), m.end(), phrase) for m in _phrase_pattern(phrase).finditer(text)]
    spans.sort()
    for (s1, e1, p1), (s2, e2, p2) in zip(spans, spans[1:]):
        if s2 < e1:
            raise PlanError(f"context sources {p1!r} and {p2!r} overlap in text {text!r}; "
                            "C2 does not define which is removed")
    if not spans:
        return text, (), False
    kept, pos = [], 0
    for start, end, _ in spans:
        kept.append(text[pos:start])
        pos = end
    kept.append(text[pos:])
    result = " ".join("".join(kept).split())                              # C2.4
    removed = tuple(p for p in phrases if any(p == sp for _, _, sp in spans))
    if not result:                                                        # C2.5
        return text, removed, True
    return result, removed, False


def plan(request: Request, unresolved: tuple[Unresolved, ...] = ()) -> Plan:
    """The IR-1 retrieval plan for one request. Pure and deterministic; performs no retrieval."""
    hard: list[HardFilter] = []
    soft: list[SoftClue] = []
    for clue in request.clues:
        strength = effective_strength(clue)
        if strength == "confirmed":                                       # M1
            hard.append(HardFilter(HARD_FILTER_KEY[clue.field], clue.code, clue))
        else:                                                             # M2 (C1 for wbs)
            soft.append(SoftClue(field=clue.field, code=clue.code, frozen_strength=clue.strength,
                                 strength=strength, boost=BOOST[strength], source=clue.source,
                                 reclassified="C1" if strength != clue.strength else None))
    by_key: dict[str, str] = {}
    for f in hard:
        if by_key.setdefault(f.key, f.code) != f.code:
            raise PlanError(f"request {request.id}: confirmed clues give two values for the {f.key!r} filter "
                            f"({by_key[f.key]!r}, {f.code!r}); M1 does not define how to combine them")
    hard = list({(f.key, f.code): f for f in hard}.values())              # one filter per key and code

    pool_text, removed, fallback = remove_context_sources(
        request.text, tuple(c.source for c in soft if c.strength == "context"))
    own_unresolved = tuple(u for u in unresolved if u.id == request.id)
    return Plan(
        request_id=request.id,
        is_default=is_default(request),
        hard_filters=tuple(hard),
        soft_clues=tuple(soft),
        pool_text=pool_text,
        relation=request.relation,
        revision_state=request.revision_state,
        document_state=request.document_state,
        audit=Audit(raw_text=request.raw_text, text=request.text, approx=request.approx,
                    verify=request.verify, withdrawn=request.withdrawn, source_file=request.source_file,
                    state_source=request.state_source, unresolved=own_unresolved,
                    removed_phrases=removed, pool_text_fallback=fallback),
    )


def plan_all(frozen: FrozenRequests) -> tuple[Plan, ...]:
    return tuple(plan(r, frozen.unresolved) for r in frozen.requests)
