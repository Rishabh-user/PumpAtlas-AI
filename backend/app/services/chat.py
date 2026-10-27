"""Answer a question from the record and from the web, and say which is which.

Three parts, deliberately kept apart:

* **What we hold.** The existing search index, so an answer about a pump we already
  track cites the record rather than re-reading the internet.
* **What the web says.** The active search provider, whose excerpts are quoted as
  evidence. Nothing here writes to the database.
* **What is new.** Web results whose vendor or model does not match anything held. These
  are the only reason a chat answer can lead to a stored record, and they are handed to
  the ordinary discovery pipeline to be captured - not written from here.

That last separation is the important one. A chat answer is model prose; it is not
evidence, and it must never become a stored field. Storing goes through the same capture
and provenance path as `/pumps` and `/vendors`, where every value carries a verbatim
quote from a page PumpAtlas fetched itself.
"""

from __future__ import annotations

import re
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import providers
from app.ai.parallel_search import SearchExcerpt
from app.core.config import settings
from app.core.logging import get_logger
from app.models.pump import Pump, PumpModel
from app.models.search import SearchIndex
from app.schemas.specs import SPEC_FIELDS
from app.services import (
    ai_settings,
    ingestion,
    parsing,
    promotion,
    question_filters,
    records,
    search,
)
from app.services.search import SearchFilters

log = get_logger(__name__)

#: How much of the record to put in front of the model. Enough to answer from, small
#: enough that the page text still fits.
MAX_RECORDS = 8

#: How many web results to quote. Each excerpt can be several thousand characters.
MAX_WEB_RESULTS = 5

#: Excerpt characters per source. Beyond this the answer is no better and the call is
#: slower and dearer.
MAX_EXCERPT_CHARS = 3_000

SYSTEM_PROMPT = """You are a pump procurement assistant for Oil & Gas engineering.

You are given two kinds of context:

RECORDS - rows already held in this platform's database. Authoritative.
WEB - excerpts from pages found just now by a web search. Unverified.

Rules:
- Answer only from the context given. If it does not contain the answer, say so plainly.
- Cite every claim with the marker of its source, like [R1] for a record or [W2] for a
  web excerpt. A sentence with no marker will be treated as unsupported.
- When the record and the web disagree, say both and say which is which.
- Never invent a model code, a capacity, a pressure rating or a price. If a figure is
  not in the context, say it is not stated.
- Cite only markers that actually appear in the context. If no records and no web
  excerpts were given, say so plainly and cite nothing: writing [R1] to satisfy the
  citation rule invents the very source the rule exists to demand, and the reader
  cannot tell the difference.
- A record lists only the fields it actually holds. If a field is absent from a record,
  that field is not recorded for it - say so, and do not read it as a zero or carry it
  over from a sibling record.
- Be brief and concrete. An engineer is reading this to make a decision.
"""


#: Words that carry no signal in a question about pumps. Not a general stopword list -
#: it also drops the vocabulary of asking ("which", "show", "tell"), because those are
#: what makes a question a question rather than a query.
_NOISE = frozenset(
    """
    a an and any are as at be by can do does for from get give has have how i in into is
    it its list me my of on or our please show tell that the their them there these this
    to us was we what when where which who why will with you your pump pumps
    """.split()
)

_WORD = re.compile(r"[a-z0-9][a-z0-9./-]*", re.IGNORECASE)

#: Enough terms to find the record, few enough that the query stays selective.
MAX_QUERY_TERMS = 8


def record_query(question: str) -> str:
    """The question, rewritten as something the full-text index can match.

    `websearch_to_tsquery` ANDs every word, so a whole sentence matches nothing: asking
    "which Sulzer multistage pumps do we hold and what is their rated head?" found zero
    rows while "Sulzer" alone found seven. The content words are OR-ed instead and the
    index's own ranking decides the order, which is what it is for.
    """
    words = [w.lower() for w in _WORD.findall(question)]
    terms: list[str] = []
    for word in words:
        if len(word) < 3 or word in _NOISE or word in terms:
            continue
        terms.append(word)
        if len(terms) >= MAX_QUERY_TERMS:
            break
    # No content words at all ("what do we have?") - let the index match nothing rather
    # than returning the whole table as if it were relevant.
    return " or ".join(terms)


#: The questions the Ask screen offers, and the ones an opening greeting suggests.
#: Defined here rather than in the route so the screen's chips and the assistant's own
#: suggestions cannot drift apart - they were two lists saying the same thing.
EXAMPLE_QUESTIONS: list[dict[str, str]] = [
    # ---- answerable from the record ------------------------------------------------
    #
    # Chosen against what the catalogue actually holds, which is a narrower thing than
    # what it tracks. 1,684 suppliers carry a country and a tier; 82 of 160 models carry
    # technical specifications; four carry commercial ones. A question about price or
    # lead time comes back empty not because the question is bad but because nobody has
    # been quoted yet - so none of these ask one.
    {
        "mode": "record",
        "label": "Suppliers in Singapore",
        "query": "Which suppliers do we hold in Singapore, and how many are approved?",
    },
    {
        "mode": "record",
        "label": "Approved vs pending",
        "query": (
            "How many suppliers are approved versus pending qualification, and "
            "who approved them?"
        ),
    },
    {
        "mode": "record",
        "label": "Tier 1 OEMs",
        "query": (
            "List our Tier 1 OEM suppliers and the product families they are " "recorded against."
        ),
    },
    {
        "mode": "record",
        "label": "OH2 overhung pumps",
        "query": "Which API 610 OH2 pump models do we hold, and who makes them?",
    },
    {
        "mode": "record",
        "label": "Between-bearings models",
        "query": "What BB2 and BB3 between-bearings models are in the catalogue?",
    },
    {
        "mode": "record",
        "label": "Vertically suspended",
        "query": "Show me the VS4 and VS6 vertically suspended pumps we have recorded.",
    },
    {
        "mode": "record",
        "label": "Indian suppliers with GST",
        "query": (
            "Which Indian suppliers do we hold, and which of them have a GST " "number on record?"
        ),
    },
    {
        "mode": "record",
        "label": "Models with duty data",
        "query": (
            "Which pump models have technical specifications recorded, and "
            "which are still empty?"
        ),
    },
    {
        "mode": "record",
        "label": "Suppliers missing a website",
        "query": "Which approved suppliers have no website recorded?",
    },
    {
        "mode": "record",
        "label": "Where a value came from",
        "query": (
            "For the Flowserve ECPJ, what is recorded and which source did " "each value come from?"
        ),
    },
    # ---- the web is the only place these are answered ------------------------------
    #
    # A manufacturer publishes duty curves, materials and configuration. It does not
    # publish a price, a lead time or an on-time delivery record, so no question here
    # asks for one: ten measured enrichment runs returned none of the three.
    {
        "mode": "web",
        "label": "Find a datasheet",
        "query": (
            "Find the datasheet for the Sulzer MSD multistage pump and tell me its "
            "duty range and materials."
        ),
    },
    {
        "mode": "web",
        "label": "Barrel pumps for crude export",
        "query": "Who makes API 610 BB5 barrel pumps suitable for crude export duty?",
    },
    {
        "mode": "web",
        "label": "Sour service compliance",
        "query": (
            "Which pump manufacturers state NACE MR0175 compliance for sour service, "
            "and where do they say it?"
        ),
    },
    {
        "mode": "web",
        "label": "Seal plans for hot hydrocarbon",
        "query": (
            "What API 682 seal arrangements and flush plans are recommended for "
            "hot hydrocarbon service?"
        ),
    },
    {
        "mode": "web",
        "label": "Materials for sulphur service",
        "query": (
            "What casing and impeller materials do manufacturers specify for "
            "molten sulphur service?"
        ),
    },
    {
        "mode": "web",
        "label": "Suppliers in a region",
        "query": "Which Oil & Gas pump manufacturers have manufacturing in South East Asia?",
    },
    {
        "mode": "web",
        "label": "Hazardous area certification",
        "query": (
            "Which pump manufacturers publish ATEX and IECEx certification for " "Zone 1 equipment?"
        ),
    },
    {
        "mode": "web",
        "label": "API 610 versus ISO 13709",
        "query": (
            "What is the difference between API 610 and ISO 13709, and does a pump "
            "certified to one satisfy the other?"
        ),
    },
    {
        "mode": "web",
        "label": "Sea water injection",
        "query": (
            "Which manufacturers build sea water injection pumps for FPSO duty, "
            "and in what materials?"
        ),
    },
    {
        "mode": "web",
        "label": "Vertical sump pumps",
        "query": (
            "Find vertical sump pump ranges rated above 500 m3/h and tell me which "
            "standards they are built to."
        ),
    },
]

#: Openings that are not questions about pumps. Matched against the whole message, not
#: searched for inside it, so "hi there" is a greeting while "hi-flow pump seals" is not.
_GREETINGS = frozenset(
    {
        # One-word openings.
        "hi",
        "hii",
        "hiya",
        "hello",
        "helo",
        "hey",
        "heya",
        "yo",
        "sup",
        "greetings",
        "namaste",
        "howdy",
        "morning",
        "evening",
        # Two- and three-word openings, kept whole because "there" and "all" are
        # meaningless on their own.
        "hi there",
        "hello there",
        "hey there",
        "hi all",
        "hello all",
        "hi team",
        "good morning",
        "good afternoon",
        "good evening",
        "good day",
        "whats up",
    }
)

#: Asking after the assistant rather than greeting it. Separate because "Hello." is the
#: wrong answer to "how are you" - it ignores what was actually asked.
_WELLBEING = frozenset(
    {
        "how are you",
        "how are you doing",
        "how r u",
        "hows it going",
        "how is it going",
        "you ok",
        "you okay",
        "are you there",
        "you there",
        "are you working",
        "still there",
    }
)
_THANKS = frozenset(
    {"thanks", "thank you", "thanks a lot", "thank you so much", "thx", "ty", "cheers"}
)
_FAREWELLS = frozenset({"bye", "goodbye", "good bye", "see you", "see ya", "that is all"})
_CAPABILITY = frozenset(
    {
        "what can you do",
        "what do you do",
        "who are you",
        "what are you",
        "what is this",
        "help",
        "how does this work",
    }
)

#: Strip punctuation and anything that is not a letter, digit or space, so "Hi there!!"
#: and "hi there" are the same opening.
_PUNCTUATION = re.compile(r"[^a-z0-9\s]+")


#: How people address whoever they are talking to. Dropped from the end of an opening so
#: "hi bro", "hello mate" and "hey team" are the one greeting they obviously are, rather
#: than one entry each in a list that could never be finished.
_ADDRESS_TERMS = frozenset(
    {
        "bro",
        "bruh",
        "buddy",
        "mate",
        "dude",
        "man",
        "sir",
        "madam",
        "maam",
        "boss",
        "team",
        "guys",
        "everyone",
        "all",
        "friend",
        "there",
        "ji",
    }
)


def _openings(question: str) -> tuple[str, ...]:
    """The message as written, and again with any form of address dropped.

    Both, because stripping can destroy the phrase being matched: "are you there" is a
    question about the assistant, and dropping its "there" as a form of address leaves
    "are you", which is nothing. Matching the written form first keeps the phrase, and
    the stripped form still catches "hi there" and "hello bro".
    """
    words = _PUNCTUATION.sub(" ", question.lower()).split()
    plain = " ".join(words)
    # Only from the end, and never all of them: "bro" alone stays "bro".
    while len(words) > 1 and words[-1] in _ADDRESS_TERMS:
        words.pop()
    stripped = " ".join(words)
    return (plain,) if stripped == plain else (plain, stripped)


def _suggestion_lines() -> str:
    return "\n".join(f"- {example['query']}" for example in EXAMPLE_QUESTIONS)


def conversational_reply(question: str) -> str | None:
    """A written reply for a message that is not a question to search, or None.

    Without this, "hi there" went through the full pipeline: `record_query` reduces it
    to nothing ("hi" is too short, "there" is a stopword), so no record matched, and the
    web was then searched for the literal words - which returned a Wiktionary entry for
    the interjection and a Quora thread about the difference between "hi" and "hi
    there". Accurate retrieval of entirely the wrong thing, and it cost a real search.

    Matching is against the whole normalised message rather than a substring, so a
    greeting is a greeting and a question that happens to contain one is still a
    question.
    """
    openings = _openings(question)
    if not openings[0]:
        return None

    def said(phrases: frozenset[str]) -> bool:
        return any(opening in phrases for opening in openings)

    if said(_GREETINGS):
        return (
            "Hello. I answer questions about the pumps, vendors, duties and standards "
            "this catalogue holds, and I search the web alongside it. Every claim is "
            "marked with where it came from - **[R1]** for a held record, **[W1]** for "
            "a web page.\n\n"
            "What would you like to know? For example:\n\n"
            f"{_suggestion_lines()}\n\n"
            "You can also name a vendor, a model code, a standard or a duty point and "
            "I will tell you what is recorded against it."
        )

    if said(_WELLBEING):
        return (
            "Running, and connected to the catalogue. Ask me anything about the pumps, "
            "vendors, duties or standards it holds.\n\n"
            f"{_suggestion_lines()}"
        )

    if said(_CAPABILITY):
        return (
            "I answer questions about this pump catalogue - what is held against a "
            "vendor, a model, a standard or a duty - and search the web for what is "
            "not held yet. I read only: asking writes nothing.\n\n"
            "I do not rank or score vendors. For a scored shortlist use Vendor "
            "Shortlist.\n\n"
            "Try one of these:\n\n"
            f"{_suggestion_lines()}"
        )

    if said(_THANKS):
        return "You are welcome. Ask me anything else about the catalogue."

    if said(_FAREWELLS):
        return "Goodbye."

    return None


#: The vocabulary of the domain: rotating equipment, the standards that govern it, the
#: duties it is bought for and the places it is installed. Single words, matched against
#: the question's own tokens.
#:
#: Deliberately wide. A question wrongly refused is worse than an odd one answered: the
#: first makes the assistant look broken to the person it was built for, the second
#: costs one search.
#:
#: Wide, but not at the cost of a collision. "hi" was in here for the Hydraulic
#: Institute and it let "Hi bro" through the gate to be web-searched as a phrase - a
#: two-letter abbreviation is not worth what it costs when it is also how people say
#: hello. Nobody writes it bare anyway; they write "HI 14.6" or "Hydraulic Institute",
#: and both still match.
_DOMAIN_TERMS = frozenset(
    """
    pump pumps pumping impeller impellers casing casings volute diffuser shaft bearing
    bearings seal seals sealing gland packing coupling couplings driver motor motors
    turbine engine gearbox baseplate skid stuffing wear rings balance thrust
    npsh npshr npsha cavitation head flow flowrate capacity duty duties discharge
    suction pressure barg bara psi temperature viscosity density specific gravity
    efficiency bep rpm speed power kw hp stage stages multistage single double
    centrifugal reciprocating rotary positive displacement screw gear diaphragm
    peristaltic submersible booster metering dosing injection circulating transfer
    api iso ansi asme nace atex iecex din nema mr0175 mr0103 15156 13709 610 611
    674 675 676 681 682 685 51 53 21049 barrel between bearings overhung vertically
    suspended vertical horizontal inline sump canned magnetic drive sealless
    bb1 bb2 bb3 bb4 bb5 oh1 oh2 oh3 oh4 oh5 oh6 vs1 vs2 vs3 vs4 vs5 vs6 vs7
    oil gas oilfield petroleum petrochemical refinery refining upstream midstream
    downstream crude condensate hydrocarbon lng ngl naphtha diesel kerosene
    offshore onshore subsea topside platform fpso fso rig wellhead drilling
    production separator manifold pipeline export import loading terminal
    sour sweet h2s sulphide sulfide corrosion corrosive erosion slurry
    amine glycol meg teg methanol produced water injection disposal flooding
    boiler feed condensate cooling firewater deluge ballast bilge cargo
    lube lubrication hydraulic chemical process utility
    vendor vendors supplier suppliers manufacturer manufacturers oem fabricator
    datasheet datasheets specification specifications spec catalogue catalog
    model models series range type types code codes standard standards compliant
    compliance certified certification certificate approval approved qualification
    material materials metallurgy duplex super austenitic stainless steel alloy
    hastelloy inconel monel titanium bronze cast ductile carbon chrome
    lead time delivery price cost budget quotation rfq itb tender bid shortlist
    installed units mtbf reliability availability maintenance overhaul spares
    acceptance tolerance tolerances witness hydrostatic curve curves performance
    """.split()
)

#: Model and type codes the vocabulary cannot list: "HPX4x6", "3409L", "PWI-BB". A token
#: carrying both letters and digits is an equipment designation far more often than it is
#: ordinary English, which is why a bare word is not enough on its own.
_CODE_LIKE = re.compile(r"^(?=.*[a-z])(?=.*\d)[a-z0-9][a-z0-9./x-]{2,}$", re.IGNORECASE)


def domain_signal(question: str) -> bool:
    """Whether the question is about oil and gas rotating equipment at all.

    Consulted only when the catalogue matched nothing. A question that matched a record
    is in the domain by construction - PumpAtlas holds the thing being asked about - so
    the vocabulary never has to be complete enough to recognise every model code, and a
    vendor or model the catalogue knows can never be refused.
    """
    for word in (w.lower() for w in _WORD.findall(question)):
        if word in _DOMAIN_TERMS or _CODE_LIKE.match(word):
            return True
    return False


def off_domain_reply() -> str:
    """Said when a question is answerable, but not by this assistant."""
    return (
        "I only answer questions about oil and gas pumps - the equipment, the vendors "
        "that make it, the standards it is built to and the duties it is bought for. "
        "That question is outside it, so I have not searched.\n\n"
        "Ask me something like:\n\n"
        f"{_suggestion_lines()}"
    )


def clarification_reply(question: str) -> str:
    """What to say when a message carries nothing searchable.

    Reached when `record_query` finds no content word - "what do we have?" and the like.
    Searching the web for those words finds pages about the words, not about pumps, so
    it is better to ask for the missing detail than to spend a search proving it.
    """
    del question
    return (
        "I could not find anything in that to search for - no vendor, model, standard "
        "or duty.\n\n"
        "Tell me one of those and I will look. For example:\n\n"
        f"{_suggestion_lines()}"
    )


#: The panels a pump profile is read in, in the order the profile page shows them. The
#: chat answers in the same shape deliberately: someone comparing a chat result against
#: a record should not have to translate between two layouts.
GROUP_LABELS: dict[str, str] = {
    "attributes": "Pump attributes",
    "technical": "Technical",
    "commercial": "Commercial",
    "dimensional": "Weights & dimensions",
    "delivery": "Delivery",
    "operational": "Operational track record",
    "administrative": "Administrative & compliance",
}

#: Identity held on the model row rather than in a spec table.
MODEL_ATTRIBUTE_FIELDS = (
    "model_code",
    "size_designation",
    "frame_size",
    "stages",
    "orientation",
    "generation",
    "tag_number",
    "project_reference",
)

#: Attributes of the pump family, shared by every model variant under it.
PUMP_ATTRIBUTE_FIELDS = (
    "product_family",
    "pump_type",
    "pump_type_raw",
    "applicable_standard",
    "standard_edition",
    "additional_standards",
    "service_application",
    "handled_fluids",
    "is_discontinued",
)

#: Prose, kept out of the field list: a paragraph is not a value.
PROSE_FIELDS = ("description", "ai_summary")

#: Recorded fields per record put in front of the model. A fully populated record is
#: about sixty and eight of those still fits comfortably - but one record with a hundred
#: array entries should not crowd out the web half.
MAX_CONTEXT_FIELDS = 60

#: Columns that describe the spec row rather than the pump. `records.META_COLUMNS`
#: already drops the identifiers and the version bookkeeping; these are the ones it
#: keeps because a flattened record wants them, and a specification panel does not.
#: Left in, they read as pump data - "Technical: confidence_level ai_extracted" - and
#: the model was being handed them as if they were a duty point.
ROW_META_COLUMNS = frozenset(
    {
        "confidence_level",
        "verification_status",
        "data_submission_date",
        "signal_list",
        "notes",
    }
)


def _present(pairs: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    """The pairs that hold a value, as field rows.

    Empty is not a value, and that includes an empty dict: an unpopulated JSON column
    comes back as ``{}``, which is not ``None`` and would otherwise be shown as a
    recorded field holding nothing.
    """
    return [
        {"field_name": name, "value": records.to_jsonable(value)}
        for name, value in pairs
        if name not in ROW_META_COLUMNS
        and value is not None
        and value != ""
        and value != []
        and value != {}
    ]


def record_details(db: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The matched records with every field they hold, grouped as the profile page groups.

    The search index carries a summary - two dozen columns chosen to rank a row - and
    answering from it means answering "not stated" about figures the record does hold,
    because casing design pressure, warranty months and shipping weight are not in the
    index. So the spec tables are read for the matched models and the answer is grounded
    on the whole record.

    The cost is flat: one query for the pump and model rows and six for the spec groups,
    however many records matched.
    """
    ids: list[uuid.UUID] = []
    for row in rows:
        try:
            ids.append(uuid.UUID(str(row["pump_model_id"])))
        except (KeyError, ValueError):
            continue
    if not ids:
        return []

    pairs = {
        model.id: (model, pump)
        for model, pump in db.execute(
            select(PumpModel, Pump)
            .join(Pump, Pump.id == PumpModel.pump_id)
            .where(PumpModel.id.in_(ids))
        ).all()
    }
    specs = records.current_specs_bulk(db, ids)

    details: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        try:
            model_id = uuid.UUID(str(row["pump_model_id"]))
        except (KeyError, ValueError):
            continue

        groups: list[dict[str, Any]] = []
        notes: list[str] = []
        pair = pairs.get(model_id)
        if pair is not None:
            model, pump = pair
            attributes = _present(
                [(name, getattr(model, name, None)) for name in MODEL_ATTRIBUTE_FIELDS]
                + [(name, getattr(pump, name, None)) for name in PUMP_ATTRIBUTE_FIELDS]
            )
            groups.append(
                {
                    "key": "attributes",
                    "label": GROUP_LABELS["attributes"],
                    "fields": attributes,
                    "recorded": len(attributes),
                    "tracked": len(MODEL_ATTRIBUTE_FIELDS) + len(PUMP_ATTRIBUTE_FIELDS),
                }
            )
            notes = [
                str(value)
                for value in (getattr(pump, name, None) for name in PROSE_FIELDS)
                if value
            ]

        for group in records.SPEC_CLASSES:
            spec = (specs.get(model_id) or {}).get(group)
            values = records.spec_values(spec) if spec is not None else {}
            fields = _present(list(values.items()))
            groups.append(
                {
                    "key": group,
                    "label": GROUP_LABELS.get(group, group.title()),
                    "fields": fields,
                    "recorded": len(fields),
                    "tracked": len(
                        [
                            name
                            for name in SPEC_FIELDS.get(group, [])
                            if name not in ROW_META_COLUMNS
                        ]
                    ),
                }
            )

        details.append(
            {
                **row,
                "marker": f"R{index}",
                "groups": groups,
                "notes": notes,
                "recorded_count": sum(int(group["recorded"]) for group in groups),
            }
        )
    return details


def _record_context(details: list[dict[str, Any]]) -> str:
    """The held records, as numbered blocks the model can cite.

    Every recorded field goes in, grouped and named as the database names it. A field
    absent here is absent from the record, which is a fact the answer is allowed to
    state - and the prompt says so, because "not recorded" and "zero" are different
    answers to a procurement question.
    """
    lines: list[str] = []
    for index, detail in enumerate(details, start=1):
        # Matches the marker `record_details` assigned, which goes by the same order.
        head = (
            f"[R{index}] {detail.get('label') or detail.get('model_code') or 'pump model'}"
            f" | vendor: {detail.get('vendor_name') or 'unknown'}"
        )
        written = 0
        body: list[str] = []
        for group in detail.get("groups") or []:
            rendered: list[str] = []
            for field in group["fields"]:
                if written >= MAX_CONTEXT_FIELDS:
                    break
                rendered.append(f"{field['field_name']}: {field['value']}")
                written += 1
            if rendered:
                body.append(f"  {group['label']} - " + "; ".join(rendered))
        if not body:
            body.append("  no fields recorded")
        lines.append("\n".join([head, *body]))
    return "\n".join(lines)


#: A page the chat reads itself is read briefly or not at all: the caller is waiting,
#: and five pages fetched one after another at the crawler's 45s ceiling would outlast
#: any reasonable patience. Short, bounded, and concurrent.
WEB_READ_TIMEOUT_SECONDS = 6
WEB_READ_WORKERS = 5

#: A wall-clock ceiling on the whole page-reading phase.
#:
#: `WEB_READ_TIMEOUT_SECONDS` is httpx's *read* timeout, which restarts on every chunk -
#: so a server that trickles bytes can hold a connection well past it, which is exactly
#: what the crawler's own 45s ceiling exists to survive. Here the caller is waiting, so
#: the phase gets a budget it cannot exceed whatever the far end does. Pages still in
#: flight when it expires are abandoned; they were bare links before and they stay bare
#: links, which costs the answer nothing it had.
WEB_READ_BUDGET_SECONDS = 7


def _read_linked_page(result: Any) -> bool:
    """Fetch one linked page and attach its text. True if it became quotable.

    Everything is caught. A page that will not load, is disallowed by robots, or parses
    to nothing simply stays a bare link - which is the state it was already in, so a
    failure here costs the answer nothing.
    """
    url = getattr(result, "url", "") or ""
    if not url.startswith(("http://", "https://")):
        return False
    try:
        if not ingestion.robots_allows(url):
            return False
        body, headers, status_code = ingestion.fetch_url(url, timeout=WEB_READ_TIMEOUT_SECONDS)
        if status_code >= 400:
            return False
        mime_type = (headers.get("content-type") or "").split(";")[0].strip() or None
        parsed = parsing.parse_bytes(body, filename=urlparse(url).path, mime_type=mime_type)
        text = (parsed.text or "").strip()
        if not text:
            return False
        result.excerpts.append(SearchExcerpt(text=text[:MAX_EXCERPT_CHARS], locator=url))
        return True
    except Exception as exc:  # noqa: BLE001 - a link that will not read stays a link
        log.info("chat.page_read_failed", url=url[:120], error=str(exc)[:120])
        return False


def _read_linked_pages(results: list[Any]) -> int:
    """Read every result the provider returned without text. Returns how many worked.

    Concurrent because they are independent and the caller is waiting: five pages in
    sequence is five timeouts deep, five in parallel is one.
    """
    pending = [r for r in results if not _readable(r)]
    if not pending:
        return 0

    pool = ThreadPoolExecutor(max_workers=WEB_READ_WORKERS)
    futures = [pool.submit(_read_linked_page, result) for result in pending]
    read = 0
    try:
        for future in as_completed(futures, timeout=WEB_READ_BUDGET_SECONDS):
            if future.result():
                read += 1
    except FuturesTimeout:
        abandoned = sum(1 for future in futures if not future.done())
        log.info("chat.page_read_budget_spent", abandoned=abandoned)
    finally:
        # Not waited on: a thread still blocked on a slow server would put the caller
        # right back where this budget exists to stop them being.
        pool.shutdown(wait=False, cancel_futures=True)
    return read


def _readable(result: Any) -> bool:
    """Whether the provider actually returned page text for this result.

    Not a quality judgement - a short excerpt is still evidence. It only separates a
    page that was fetched and read from a bare link, because the second cannot support
    a claim however plausible its title looks.
    """
    return bool((getattr(result, "combined_excerpt", "") or "").strip())


def _web_context(results: list[Any]) -> str:
    """The web excerpts, as numbered blocks the model can cite."""
    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        excerpt = (getattr(result, "combined_excerpt", "") or "")[:MAX_EXCERPT_CHARS]
        title = getattr(result, "title", None) or result.url
        lines.append(f"[W{index}] {title}\nURL: {result.url}\n{excerpt}".strip())
    return "\n\n".join(lines)


def _held_names(db: Session) -> set[str]:
    """Normalised vendor names already in the record, for the "is this new" test.

    Uses the same normaliser the vendor resolver uses, so "Sulzer Pumps Ltd." and
    "sulzer pumps" are one name here exactly as they are one row there.
    """
    rows = search.search_pump_models(db, SearchFilters(), limit=500)[0]
    names = {
        promotion.normalize_company_name(row["vendor_name"])
        for row in rows
        if row.get("vendor_name")
    }
    names.discard("")
    return names


_VENDOR_HINT = re.compile(
    r"\b(sulzer|flowserve|baker hughes|schlumberger|slb|halliburton|weir|itt|goulds|"
    r"ruhrpumpen|ksb|grundfos|ebara|torishima|sundyne|nikkiso|pumpworks|apollo|"
    r"idex|milton roy|pulsafeeder|leistritz|bornemann|netzsch|seepex|colfax)\b",
    re.IGNORECASE,
)


def _looks_new(result: Any, held: set[str]) -> str | None:
    """The vendor this page seems to be about, when we do not already hold it.

    A cheap heuristic on the title and URL, not an extraction: deciding properly means
    reading the page, which is what capture does. This only decides whether a page is
    *worth* offering to capture, so a false positive costs a suggestion and a false
    negative costs nothing that the ordinary AI search would not also find.
    """
    haystack = f"{getattr(result, 'title', '') or ''} {result.url}"
    match = _VENDOR_HINT.search(haystack)
    if match is None:
        return None
    name = match.group(0)
    return None if promotion.normalize_company_name(name) in held else name


def _duty_coverage(db: Session, keys: list[str]) -> str:
    """How many indexed records state each duty figure the question asked about.

    One query, run only when a duty filter has already come back empty. The sentence it
    produces is the difference between "nothing matches your 200 m3/h requirement" -
    which reads as *we have no such pump* - and the truth, which is that almost no
    record states a flow rate at all.
    """
    columns = [question_filters.DUTY_COLUMNS[k] for k in keys if k in question_filters.DUTY_COLUMNS]
    if not columns:
        return ""
    selected = [func.count(getattr(SearchIndex, c)).label(c) for c in columns]
    row = (
        db.execute(select(func.count().label("total"), *selected).select_from(SearchIndex))
        .mappings()
        .one()
    )
    total = row["total"] or 0
    if not total:
        return ""
    parts = [
        f"{row[question_filters.DUTY_COLUMNS[k]]} state a {question_filters.DUTY_LABELS[k].lower()}"
        for k in keys
        if k in question_filters.DUTY_COLUMNS
    ]
    return f"Of {total} indexed records, " + ", ".join(parts) + "."


#: A citation as the prose writes it, with any space that runs up to it.
_MARKER = re.compile(r"[ \t]*\[([RW]\d+)\]")


def _strip_unknown_markers(prose: str, known: set[str]) -> tuple[str, list[str]]:
    """Remove citations pointing at sources that were never given.

    The system prompt says to cite every claim, and a model with nothing to cite
    satisfies that rule by inventing a marker: asked which Brazilian pumps are held,
    with no records matched, it answered "we do not hold any pumps from Brazil [R1]".
    There is no R1. The sentence is true and the citation is fabricated, which is worse
    than an uncited sentence - the page renders markers as references to real records,
    so a reader sees evidence where none exists.

    Tightening the prompt fixed one question and not the next, which is what prompts
    do. This is checkable, so it is checked: a marker survives only if the context
    actually carried that source.
    """
    dropped: list[str] = []

    def keep(match: re.Match[str]) -> str:
        if match.group(1) in known:
            return match.group(0)
        dropped.append(match.group(1))
        return ""

    return _MARKER.sub(keep, prose), dropped


def _search_question(
    db: Session, parsed: question_filters.Parsed
) -> tuple[list[Any], int, list[str]]:
    """Search on what the question asked for, relaxing rather than returning zero.

    Two clauses in this search are AND-ed, and each can empty the result on its own:

    * A numeric filter excludes a row whose column is NULL, which is the right SQL and
      the wrong answer here - 6 of 166 indexed records state a flow rate, so filtering
      on one empties the catalogue.
    * The free-text half matches against the record *label*. Words like "suppliers" or
      "hold" appear in no label, so the leftovers of a question can zero out a filter
      that was perfectly correct. Asked for suppliers held in Singapore, the filter
      found the 6 Singaporean records and the word "suppliers" then threw them away.

    So the search is tried as a ladder, widest requirement first, and every rung given
    up is reported. The reader is told what was dropped; they are never handed an empty
    answer that reads as *we have no such pump* when the truth is that the question
    asked about a column the catalogue does not fill in.

    Categorical filters are the one thing never relaxed. A vendor with no country
    recorded genuinely cannot be shown as Singaporean, and pretending otherwise is the
    error this whole module exists to stop.
    """

    # Once a country, type or standard has been recognised, the filters say what the
    # question asked for and the leftover words are the grammar of asking. They order
    # the answer; they do not get to throw records out of it.
    narrows = not parsed.categorical_named

    def run(filters: SearchFilters) -> tuple[list[Any], int]:
        return search.search_pump_models(
            db,
            filters,
            sort="relevance",
            limit=MAX_RECORDS,
            text_narrows=narrows,
        )

    hits, total = run(parsed.filters)
    if hits or not parsed.understood:
        # Nothing was recognised, so there is no filter to blame and nothing to relax:
        # an empty result here is an ordinary empty result.
        return hits, total, []

    notes: list[str] = []
    duty = [k for k in question_filters.DUTY_LABELS if k in parsed.understood]

    # Rung two: keep every filter, drop the leftover words. Only reachable where the
    # words were narrowing in the first place - that is, where nothing categorical was
    # recognised and the free text is all the question gave.
    if parsed.filters.query and narrows:
        without_text = replace(parsed.filters, query=None)
        hits, total = run(without_text)
        if hits:
            notes.append(
                f"No record label matches the words "
                f"{_quoted(parsed.filters.query)}, so the answer is drawn from the "
                "structured filters alone."
            )
            return hits, total, notes
    else:
        without_text = parsed.filters

    # Rung three: give up the duty point, which the catalogue mostly does not record.
    if duty:
        widest = replace(without_text, **{f: None for f in question_filters.DUTY_FIELDS})
        hits, total = run(widest)
        named = ", ".join(question_filters.DUTY_LABELS[k] for k in duty)
        notes.append(
            f"No held record states {named} within the range asked for, so that part "
            f"of the requirement was set aside. {_duty_coverage(db, duty)} The records "
            "below match the rest of the question only, and have not been shown to "
            "meet the duty point."
        )
        return hits, total, notes

    # Every rung tried. The filters themselves are what found nothing, which is a real
    # answer: say which ones, so it does not read as a failed search.
    notes.append(
        "Nothing held matches "
        f"{question_filters.describe(parsed.understood)}. That is the catalogue's "
        "answer, not a failed search."
    )
    return hits, total, notes


def _quoted(query: str) -> str:
    """The free-text terms as a reader would say them, without the query syntax."""
    words = [w for w in query.split() if w.lower() != "or"]
    return ", ".join(f"\u201c{w}\u201d" for w in words)


def _web_phase(client: Any, question: str) -> tuple[list[Any], str | None]:
    """Search the web and read what comes back. Returns (results, error).

    Deliberately touches no database, which is what lets it run on another thread while
    the record half queries. A SQLAlchemy Session is not thread-safe; HTTP is.
    """
    try:
        run = client.search(
            # The objective asks for sources explicitly because of how the OpenAI
            # provider works: it has no result list, and its own module says so - the
            # pages come back as `url_citation` annotations, so the citations *are* the
            # results. A model that answers from memory cites nothing and the search
            # returns zero results with no error. Asking for manufacturer pages makes
            # citing the obvious way to answer.
            f"Oil and gas pump procurement question: {question}. "
            "Cite the manufacturer, distributor or datasheet pages used.",
            [question],
            max_results=MAX_WEB_RESULTS,
        )
        results = list(run.results)
    except Exception as exc:  # noqa: BLE001 - the record half must still answer
        log.warning("chat.web_search_failed", error=str(exc)[:200])
        return [], f"Web search failed: {type(exc).__name__}: {exc}"[:300]

    if results and settings.CHAT_READ_LINKED_PAGES:
        # Turn the bare links into sources before anything decides which are citable,
        # rather than discarding them for a lack of text the provider was never going
        # to give.
        recovered = _read_linked_pages(results)
        if recovered:
            log.info("chat.pages_read", count=recovered)
    return results, None


def answer(
    db: Session,
    question: str,
    *,
    use_web: bool = True,
    tenant_id: Any = None,
) -> dict[str, Any]:
    """Answer one question. Returns the prose, its citations, and what looked new.

    Writes nothing. The ``new_on_web`` entries are suggestions for capture, which the
    caller turns into an ordinary discovery run.

    The local name for the matched rows is ``hits`` rather than ``records``, which would
    shadow the ``records`` service this module imports - the same shadowing that once
    turned a discovery handler called ``select`` into a 500.
    """
    del tenant_id  # row level security scopes the search; no predicate needed here

    # A greeting is not a query. Answered before anything is searched, because the
    # searches are the damage: "hi there" reduces to no content words, matches no
    # record, and then sends the literal words to the web provider, which dutifully
    # returns a dictionary entry for the interjection. No model call either - the
    # reply is fixed text, so it is instant and costs nothing.
    spoken = conversational_reply(question)
    if spoken is not None:
        return _no_search_result(spoken)

    # A country, a standard, a pump type or a duty figure named in the question is a
    # *filter*, not a search term. The index carries each as a column, and asking the
    # column is both correct and cheaper than hoping the reading model notices
    # afterwards - which it does not: asked which suppliers we hold in Singapore, it
    # was handed every record the word-match returned and reported four vendors as
    # Singaporean whose own country field said DE, JP, AE and CA.
    parsed = question_filters.parse(question)
    terms = record_query(parsed.residue)
    if not terms and not parsed.understood:
        # Nothing searchable in the message. Ask for the missing detail rather than
        # spending a web search on words like "what do we have".
        return _no_search_result(clarification_reply(question))
    parsed.filters.query = terms or None
    if settings.CHAT_SHARED_MASTER_ONLY:
        # One catalogue, one answer. Without this the same question returns a different
        # answer to a tenant, to an API key and to platform staff - each correct about
        # what that caller may read, and indistinguishable from a broken API to whoever
        # is integrating it. `only_shared_master` narrows *within* row level security,
        # so it can only ever return fewer rows than the caller is entitled to.
        parsed.filters.only_shared_master = True
    # The web half is the long pole and needs no database: measured on one answer, the
    # provider took 6.7s and reading the pages 5.6s, while the record search and its
    # spec queries took 2.4s waiting their turn. They are independent, so they run
    # together and the record half costs nothing in wall time.
    #
    # Started only once the question already looks like a pump question. The domain
    # gate below refuses "what is the weather in Doha" precisely so a web search is not
    # spent on it, and launching before the gate would undo that - so a question with
    # no domain vocabulary falls back to running the web half afterwards, in the order
    # it always did.
    web_results: list[Any] = []
    web_error: str | None = None
    client = providers.configured_search_client(db) if use_web else None
    if use_web and client is None:
        web_error = (
            "No web search provider is active. Add one at /ai-settings, or ask again "
            "with the web turned off to answer from held records only."
        )
    looks_like_pumps = domain_signal(question)
    pool: ThreadPoolExecutor | None = None
    web_future: Future[tuple[list[Any], str | None]] | None = None
    if client is not None and looks_like_pumps:
        pool = ThreadPoolExecutor(max_workers=1)
        web_future = pool.submit(_web_phase, client, question)

    hits, record_total, search_notes = _search_question(db, parsed)

    # The domain gate, applied here rather than before the search because the search is
    # the better half of it: a question that matched a record is about oil and gas by
    # construction, whatever words it used. Only a question that matched nothing has to
    # persuade the vocabulary, so a vendor or model code the catalogue holds can never
    # be refused, and the gate costs no extra query.
    if not hits and not looks_like_pumps:
        # Nothing started: the web phase only launches when `looks_like_pumps` is true,
        # so refusing here still spends no search.
        return _no_search_result(off_domain_reply())

    details = record_details(db, hits)

    if web_future is not None:
        # By now the record half has been running alongside it, so this usually returns
        # immediately.
        web_results, web_error = web_future.result()
        if pool is not None:
            pool.shutdown()
    elif client is not None:
        # The question matched a record without using any domain vocabulary, so the
        # search was held back until the gate had passed. Rare, and sequential.
        web_results, web_error = _web_phase(client, question)

    # A result the provider could not read is a link, not a source. It used to be
    # handed to the model as a numbered block - title, URL, and an empty excerpt -
    # which is an invitation to cite it, and the model duly did: asked about Singapore
    # it returned five Google Maps *search* URLs with zero characters between them and
    # cited all five. A reader following [W3] reaches a map query, not a page, and the
    # answer looked sourced. Only what was actually read can be evidence.
    unread = [r for r in web_results if not _readable(r)]
    web_results = [r for r in web_results if _readable(r)]

    reader = providers.configured_reading_model(db)
    if reader is None:
        reader_fallback = providers.reading_model()
        reader = reader_fallback if reader_fallback.configured else None
    if reader is None:
        return {
            "answer": None,
            "error": (
                "No reading model is active, so nothing can compose an answer. Add one "
                "at /ai-settings."
            ),
            "records": details,
            "web": [_web_out(r, index) for index, r in enumerate(web_results, start=1)],
            "new_on_web": [],
            "web_error": web_error,
            "record_total": record_total,
            "understood": question_filters.describe(parsed.understood),
            "search_notes": search_notes,
        }

    # The model is told what the search actually asked for, so it does not restate the
    # question's own terms as though the records had been checked against them.
    reading = question_filters.describe(parsed.understood)
    if use_web and not web_results and not unread and web_error is None:
        # The search ran and found nothing to show. Saying so matters: an empty `web`
        # array with no error is indistinguishable from a web search that never
        # happened, and the caller has no way to tell which they got.
        search_notes = [
            *search_notes,
            "The web search returned no usable sources for this question. The active "
            "provider reports the pages a model chose to cite rather than a ranked "
            "result list, so a broad question often comes back with none.",
        ]

    if unread:
        search_notes = [
            *search_notes,
            f"{len(unread)} web result(s) were links the search provider could not "
            "read, so they are not quoted or cited. Only pages whose text was "
            "returned can support a claim.",
        ]
    context = "\n\n".join(
        part
        for part in (
            f"HOW THE RECORDS WERE SELECTED: filtered on {reading}." if reading else "",
            "\n".join(f"NOTE: {n}" for n in search_notes),
            f"RECORDS ({len(details)} of {record_total} held):\n{_record_context(details)}"
            if details
            else "RECORDS: none matched.",
            f"WEB:\n{_web_context(web_results)}" if web_results else "WEB: nothing searched.",
        )
        if part
    )

    try:
        result = reader.complete(
            SYSTEM_PROMPT,
            f"Question: {question}\n\n{context}",
            json_mode=False,
            max_tokens=1200,
        )
        prose = (result.text or "").strip()
        model_used = result.model
        known = {r["marker"] for r in details if r.get("marker")} | {
            f"W{index}" for index in range(1, len(web_results) + 1)
        }
        prose, invented = _strip_unknown_markers(prose, known)
        if invented:
            # Worth knowing about: it means the model is citing to satisfy a rule
            # rather than because it has a source.
            log.warning("chat.invented_citations", markers=invented, question=question[:120])
    except Exception as exc:  # noqa: BLE001 - report rather than 500 the page
        log.warning("chat.answer_failed", error=str(exc)[:200])
        return {
            "answer": None,
            "error": f"The reading model failed: {type(exc).__name__}: {exc}"[:300],
            "records": details,
            "web": [_web_out(r, index) for index, r in enumerate(web_results, start=1)],
            "new_on_web": [],
            "web_error": web_error,
            "record_total": record_total,
            "understood": question_filters.describe(parsed.understood),
            "search_notes": search_notes,
        }

    # Capture considers every result, read or not. Being unreadable disqualifies a
    # link from *supporting a claim*, which is what the split above is for; it does
    # not disqualify it from being a lead. Capture fetches the page itself and writes
    # a field only with a verbatim quote from what it fetched, so a link the search
    # provider declined to read can still turn into evidence by the proper route.
    candidates = [*web_results, *unread]
    held = _held_names(db) if candidates else set()
    new_on_web = [
        {"url": r.url, "title": getattr(r, "title", None), "vendor_hint": hint}
        for r in candidates
        if (hint := _looks_new(r, held)) is not None
    ]

    return {
        "answer": prose,
        "model": model_used,
        "records": details,
        "record_total": record_total,
        # What the question was read as, so a misreading is visible on the page rather
        # than buried in a plausible-sounding answer.
        "understood": reading,
        "search_notes": search_notes,
        "web": [_web_out(r, index) for index, r in enumerate(web_results, start=1)],
        "web_error": web_error,
        # Offered for capture, never stored from here: chat prose is not evidence.
        "new_on_web": new_on_web,
        "error": None,
    }


def _no_search_result(prose: str) -> dict[str, Any]:
    """An answer that was written rather than retrieved.

    Same envelope as a searched answer - the screens render one shape - with the
    evidence lists empty because there is none and none was claimed. ``model`` is
    absent deliberately: no model wrote this, and naming one would be untrue.
    """
    return {
        "answer": prose,
        "model": None,
        "records": [],
        "record_total": 0,
        "web": [],
        "web_error": None,
        "new_on_web": [],
        "understood": "",
        "search_notes": [],
        "error": None,
    }


def _web_out(result: Any, index: int) -> dict[str, Any]:
    excerpt = (getattr(result, "combined_excerpt", "") or "")[:400]
    return {
        "marker": f"W{index}",
        "url": result.url,
        "title": getattr(result, "title", None),
        "excerpt": excerpt,
        "has_text": bool(getattr(result, "combined_excerpt", "")),
    }


def web_is_available(db: Session) -> bool:
    """Whether a web search provider is active, so the screen can say so up front."""
    if not ai_settings.is_installed(db):
        return False
    return ai_settings.active_config(db, "search") is not None
