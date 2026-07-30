#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translate the SQLite trigger forms this store actually uses into PostgreSQL.

DELIBERATELY NARROW, AND THAT IS THE DESIGN. This is not a SQL translator. It
recognises the specific trigger shapes present in the source and REFUSES
anything else by name. A general-purpose translator would have to guess at
dialect it has never seen, and a guess that produces syntactically valid
PostgreSQL is far worse than a refusal: the destination would get a trigger that
runs and enforces something subtly different from the source, which no row-level
verification can detect.

So the rule matches the rest of the package -- handle what is accounted for,
fail loudly on what is not.

THE FORMS IT HANDLES, all taken from the live scitex-cards store or its
agreed-upon successor:

1. An unconditional guard::

       CREATE TRIGGER x BEFORE DELETE ON t
       BEGIN SELECT RAISE(ABORT, 'msg'); END

2. A conditional guard::

       CREATE TRIGGER x BEFORE UPDATE ON t
       WHEN OLD.a IS NOT NEW.a OR OLD.b IS NOT NEW.b
       BEGIN SELECT RAISE(ABORT, 'msg'); END

3. A self-bumping counter -- the optimistic-lock revision trigger::

       CREATE TRIGGER x AFTER UPDATE ON t
         FOR EACH ROW WHEN NEW.c = OLD.c
       BEGIN UPDATE t SET c = OLD.c + 1 WHERE id = NEW.id; END

FAITHFUL MEANS SAME MEANING, NOT SAME STRUCTURE, and form 3 is where that
bites. SQLite writes the bump as ``AFTER UPDATE`` plus a nested ``UPDATE``
only because a SQLite ``BEFORE`` trigger cannot assign to ``NEW``. PostgreSQL
can, so the faithful translation is ``BEFORE UPDATE`` with a direct assignment
-- structurally different, semantically identical, and without the nested write
the SQLite form needs. Reproducing the nested UPDATE in PostgreSQL would work
but would issue a second write per update for no reason.

TWO DIALECT DIFFERENCES THAT MATTER, and getting either wrong would produce a
trigger that fires at the wrong times rather than an error:

* PostgreSQL has no statement-level ``RAISE(ABORT, ...)`` expression. The guard
  becomes a ``plpgsql`` FUNCTION that does ``RAISE EXCEPTION``, plus a TRIGGER
  that calls it. One SQLite object becomes two PostgreSQL objects.
* SQLite's ``IS NOT`` between two values is NULL-safe inequality -- the same
  thing PostgreSQL spells ``IS DISTINCT FROM``. PostgreSQL's own ``IS NOT`` is
  reserved for ``IS NOT NULL`` / ``IS NOT TRUE`` and will not parse here.
  Translating ``IS NOT`` to ``<>`` would silently change behaviour when either
  side is NULL: ``NULL <> NULL`` is NULL, not true, so the guard would stop
  firing on exactly the rows where a column became or stopped being NULL.
"""

from __future__ import annotations

import re

from ._introspect import SchemaObject

__all__ = ["TriggerTranslationError", "translate_trigger"]


class TriggerTranslationError(Exception):
    """Raised when a trigger is not one of the recognised forms.

    Carries the trigger's name and its SQL, because the caller's next step is a
    human reading the original and deciding what the destination should do.
    """


#: A self-bumping counter: ``AFTER UPDATE`` + nested ``UPDATE`` of one column.
_BUMP_RE = re.compile(
    r"^\s*CREATE\s+TRIGGER\s+(?P<name>\w+)\s+"
    r"AFTER\s+UPDATE\s+ON\s+(?P<table>\w+)\s*"
    r"(?:FOR\s+EACH\s+ROW\s*)?"
    r"WHEN\s+NEW\.(?P<wcol>\w+)\s*=\s*OLD\.(?P=wcol)\s*"
    r"BEGIN\s+UPDATE\s+(?P=table)\s+SET\s+(?P<scol>\w+)\s*=\s*"
    r"OLD\.(?P=scol)\s*\+\s*1\s+WHERE\s+(?P<key>\w+)\s*=\s*NEW\.(?P=key)\s*;\s*"
    r"END\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)

#: The whole trigger, captured in the pieces PostgreSQL needs separately.
_TRIGGER_RE = re.compile(
    r"^\s*CREATE\s+TRIGGER\s+(?P<name>\w+)\s+"
    r"(?P<timing>BEFORE|AFTER)\s+(?P<event>DELETE|UPDATE|INSERT)\s+"
    r"ON\s+(?P<table>\w+)\s*"
    r"(?:WHEN\s+(?P<when>.+?)\s*)?"
    r"BEGIN\s+SELECT\s+RAISE\s*\(\s*ABORT\s*,\s*"
    r"(?P<quote>['\"])(?P<message>.*?)(?P=quote)\s*\)\s*;\s*END\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _translate_when(when: str) -> str:
    """Rewrite a SQLite WHEN condition into PostgreSQL.

    Only ``IS NOT`` needs changing, and only where it means NULL-safe
    inequality between two values. ``IS NOT NULL`` is left alone -- it means
    the same thing in both engines, and rewriting it to
    ``IS DISTINCT FROM NULL`` would be correct but gratuitous churn in a
    condition a human will read against the original.
    """
    return re.sub(
        r"\bIS\s+NOT\s+(?!NULL\b|TRUE\b|FALSE\b|UNKNOWN\b)",
        "IS DISTINCT FROM ",
        when,
        flags=re.IGNORECASE,
    )


def _requote_message(message: str, quote: str) -> str:
    """The message body, correctly escaped for a PostgreSQL single-quoted literal.

    WHICH ESCAPING IS ALREADY PRESENT DEPENDS ON THE SOURCE QUOTE, and getting
    this wrong corrupts the message rather than failing:

    * Source was single-quoted: any internal quote is ALREADY doubled (``don''t``),
      and PostgreSQL uses the same convention. Passing it through is correct;
      re-escaping produced ``don''''t`` -- a visibly mangled error message that
      still compiles, so nothing would have complained.
    * Source was double-quoted: internal single quotes are RAW (``don't``) and
      must be doubled before landing in a single-quoted PostgreSQL literal,
      where an unescaped quote would end the string early and produce a syntax
      error at migration time.
    """
    if quote == '"':
        return message.replace("'", "''")
    return message


def _translate_bump(match: "re.Match[str]") -> str:
    """PostgreSQL form of the self-bumping counter (form 3).

    THE CONDITION IS NOT OPTIONAL, and dropping it is the one mistake here that
    a test would not obviously catch. ``WHEN NEW.c = OLD.c`` means "only bump
    when the caller did NOT set the column itself". Assigning unconditionally
    would overwrite the value a lock-holding writer deliberately supplied,
    turning an optimistic-lock write into a silent last-write-wins. So the
    guard survives as an ``IF`` inside the function rather than being dropped
    on the grounds that a BEFORE trigger "doesn't need" the recursion
    protection the SQLite form used it for. It was doing two jobs; only one of
    them was about recursion.

    ``RETURN NEW`` is mandatory. A PostgreSQL ``BEFORE`` row trigger that
    returns NULL SKIPS THE ROW'S UPDATE ENTIRELY -- the write would vanish with
    no error, which is precisely the class of silent loss this migration exists
    to avoid.
    """
    name = match.group("name")
    table = match.group("table")
    col = match.group("scol")
    return (
        f'CREATE OR REPLACE FUNCTION "{name}_fn"() RETURNS trigger AS $$\n'
        f"BEGIN\n"
        f'  IF NEW."{col}" = OLD."{col}" THEN\n'
        f'    NEW."{col}" := OLD."{col}" + 1;\n'
        f"  END IF;\n"
        f"  RETURN NEW;\n"
        f"END;\n"
        f"$$ LANGUAGE plpgsql;\n"
        f'CREATE TRIGGER "{name}"\n'
        f'  BEFORE UPDATE ON "{table}"\n'
        f"  FOR EACH ROW\n"
        f'  EXECUTE FUNCTION "{name}_fn"();'
    )


def translate_trigger(obj: SchemaObject) -> str:
    """PostgreSQL DDL equivalent to ``obj``, or RAISE if the form is unknown.

    Returns the FUNCTION and the TRIGGER as one statement block, because in
    PostgreSQL the pair is inseparable -- a trigger without its function is a
    syntax error at creation time, and a function without its trigger silently
    enforces nothing.

    The emitted function is named ``<trigger>_fn`` so the correspondence is
    readable in ``\\df`` output; a hash or a serial would make the destination
    harder to audit against the source, which is the thing a human does after a
    migration.
    """
    if obj.kind != "trigger":
        raise TriggerTranslationError(
            f"{obj.name}: not a trigger (kind={obj.kind!r}). Only triggers are "
            f"translated here; indexes are handled separately and other object "
            f"kinds are not carried at all."
        )

    bump = _BUMP_RE.match(obj.sql or "")
    if bump is not None:
        return _translate_bump(bump)

    match = _TRIGGER_RE.match(obj.sql or "")
    if match is None:
        raise TriggerTranslationError(
            f"{obj.name} on {obj.table}: not a recognised trigger form, so it "
            f"is NOT translated. This module handles only RAISE(ABORT, ...) "
            f"guards, with or without a WHEN clause. Translating an unfamiliar "
            f"body by guesswork could produce a trigger that runs and enforces "
            f"something different from the source, which no row comparison "
            f"would catch. Port it by hand and confirm the semantics.\n"
            f"Original SQL:\n{obj.sql}"
        )

    name = match.group("name")
    timing = match.group("timing").upper()
    event = match.group("event").upper()
    table = match.group("table")
    when = match.group("when")
    message = _requote_message(match.group("message"), match.group("quote"))

    when_clause = f"\n  WHEN ({_translate_when(when.strip())})" if when else ""

    return (
        f'CREATE OR REPLACE FUNCTION "{name}_fn"() RETURNS trigger AS $$\n'
        f"BEGIN\n"
        f"  RAISE EXCEPTION '{message}';\n"
        f"END;\n"
        f"$$ LANGUAGE plpgsql;\n"
        f'CREATE TRIGGER "{name}"\n'
        f'  {timing} {event} ON "{table}"\n'
        f"  FOR EACH ROW{when_clause}\n"
        f'  EXECUTE FUNCTION "{name}_fn"();'
    )


# EOF
