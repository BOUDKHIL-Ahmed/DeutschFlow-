"""SQLite persistence layer for DeutschFlow."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path(
    os.getenv("DEUTSCHFLOW_DB_PATH") or (Path(__file__).resolve().parent / "deutschflow.db")
)
VALID_LEVELS = ("A2", "B1", "B2")
VALID_VERDICTS = ("correct", "minor_issues", "needs_work")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS vocabulary (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    german       TEXT NOT NULL,
    english      TEXT NOT NULL,
    grammar_info TEXT NOT NULL DEFAULT '',
    level        TEXT NOT NULL CHECK (level IN ('A2', 'B1', 'B2')),
    notes        TEXT NOT NULL DEFAULT '',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sentences (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    vocab_id          INTEGER NOT NULL REFERENCES vocabulary(id) ON DELETE CASCADE,
    english_prompt    TEXT NOT NULL,
    reference_german  TEXT NOT NULL,
    context_tag       TEXT NOT NULL DEFAULT '',
    structure_tag     TEXT NOT NULL DEFAULT '',
    level             TEXT NOT NULL CHECK (level IN ('A2', 'B1', 'B2')),
    is_favorite       INTEGER NOT NULL DEFAULT 0,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attempts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sentence_id         INTEGER NOT NULL REFERENCES sentences(id) ON DELETE CASCADE,
    user_translation    TEXT NOT NULL,
    verdict             TEXT NOT NULL CHECK (verdict IN ('correct', 'minor_issues', 'needs_work')),
    grammar_correct     INTEGER NOT NULL DEFAULT 0,
    semantic_accurate   INTEGER NOT NULL DEFAULT 0,
    grammar_summary     TEXT NOT NULL DEFAULT '',
    semantic_summary    TEXT NOT NULL DEFAULT '',
    score               INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    corrected_german    TEXT NOT NULL,
    grammar_feedback    TEXT NOT NULL DEFAULT '',
    word_order_feedback TEXT NOT NULL DEFAULT '',
    natural_expressions TEXT NOT NULL DEFAULT '',
    alternatives_json   TEXT NOT NULL DEFAULT '[]',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sentences_vocab_id ON sentences(vocab_id);
CREATE INDEX IF NOT EXISTS idx_sentences_favorite ON sentences(is_favorite);
CREATE INDEX IF NOT EXISTS idx_attempts_sentence_id ON attempts(sentence_id);
"""


def _resolve_db_path(db_path: Path | str | None) -> str:
    return str(db_path) if db_path is not None else str(DEFAULT_DB_PATH)


@contextmanager
def get_connection(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with foreign keys enabled and dict-like rows."""
    resolved = _resolve_db_path(db_path)
    if resolved != ":memory:":
        Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    """Create tables and indexes if they do not exist."""
    with get_connection(db_path) as conn:
        if str(db_path or DEFAULT_DB_PATH) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
        conn.executescript(SCHEMA_SQL)


def _validate_level(level: str) -> str:
    normalized = level.strip().upper()
    if normalized not in VALID_LEVELS:
        raise ValueError(f"Level must be one of {VALID_LEVELS}, got {level!r}")
    return normalized


def _decode_attempt(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["grammar_correct"] = bool(item["grammar_correct"])
    item["semantic_accurate"] = bool(item["semantic_accurate"])
    try:
        alternatives = json.loads(item.get("alternatives_json") or "[]")
        item["alternatives"] = alternatives if isinstance(alternatives, list) else []
    except json.JSONDecodeError:
        item["alternatives"] = []
    return item


# ---------------------------------------------------------------------------
# Vocabulary CRUD
# ---------------------------------------------------------------------------

def add_vocabulary(
    german: str,
    english: str,
    grammar_info: str = "",
    level: str = "B1",
    notes: str = "",
    db_path: Path | str | None = None,
) -> int:
    """Insert a vocabulary entry and return its new ID."""
    german_clean = german.strip()
    english_clean = english.strip()
    if not german_clean or not english_clean:
        raise ValueError("Both German expression and English meaning are required.")

    valid_level = _validate_level(level)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO vocabulary (german, english, grammar_info, level, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (german_clean, english_clean, grammar_info.strip(), valid_level, notes.strip()),
        )
        return int(cursor.lastrowid)


def list_vocabulary(
    search: str = "",
    level: str = "All",
    db_path: Path | str | None = None,
) -> list[dict]:
    """Return vocabulary entries filtered by search text and CEFR level."""
    clauses: list[str] = []
    params: list[str] = []

    if level and level != "All":
        clauses.append("level = ?")
        params.append(_validate_level(level))

    query = search.strip()
    if query:
        like = f"%{query}%"
        clauses.append("(german LIKE ? OR english LIKE ? OR grammar_info LIKE ? OR notes LIKE ?)")
        params.extend([like, like, like, like])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, german, english, grammar_info, level, notes, created_at, updated_at
            FROM vocabulary
            {where_sql}
            ORDER BY updated_at DESC, id DESC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def get_vocabulary(vocab_id: int, db_path: Path | str | None = None) -> dict | None:
    """Fetch a single vocabulary entry by ID."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, german, english, grammar_info, level, notes, created_at, updated_at
            FROM vocabulary
            WHERE id = ?
            """,
            (vocab_id,),
        ).fetchone()
        return dict(row) if row else None


def update_vocabulary(
    vocab_id: int,
    german: str,
    english: str,
    grammar_info: str,
    level: str,
    notes: str = "",
    db_path: Path | str | None = None,
) -> bool:
    """Update an existing vocabulary entry. Returns True if a row was updated."""
    german_clean = german.strip()
    english_clean = english.strip()
    if not german_clean or not english_clean:
        raise ValueError("Both German expression and English meaning are required.")

    valid_level = _validate_level(level)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE vocabulary
            SET german = ?,
                english = ?,
                grammar_info = ?,
                level = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (german_clean, english_clean, grammar_info.strip(), valid_level, notes.strip(), vocab_id),
        )
        return cursor.rowcount > 0


def delete_vocabulary(vocab_id: int, db_path: Path | str | None = None) -> bool:
    """Delete a vocabulary entry and its cascaded sentences/attempts."""
    with get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM vocabulary WHERE id = ?", (vocab_id,))
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Sentences & Favorites
# ---------------------------------------------------------------------------

def create_sentence(
    vocab_id: int,
    english_prompt: str,
    reference_german: str,
    level: str,
    context_tag: str = "",
    structure_tag: str = "",
    db_path: Path | str | None = None,
) -> int:
    """Store a generated English challenge sentence linked to a vocabulary item."""
    valid_level = _validate_level(level)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO sentences (
                vocab_id, english_prompt, reference_german, context_tag, structure_tag, level
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                vocab_id,
                english_prompt.strip(),
                reference_german.strip(),
                context_tag.strip(),
                structure_tag.strip(),
                valid_level,
            ),
        )
        return int(cursor.lastrowid)


def get_sentence(sentence_id: int, db_path: Path | str | None = None) -> dict | None:
    """Fetch a sentence joined with its target vocabulary metadata."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                s.id,
                s.vocab_id,
                s.english_prompt,
                s.reference_german,
                s.context_tag,
                s.structure_tag,
                s.level,
                s.is_favorite,
                s.created_at,
                v.german AS vocab_german,
                v.english AS vocab_english,
                v.grammar_info AS vocab_grammar_info,
                v.level AS vocab_level
            FROM sentences s
            JOIN vocabulary v ON v.id = s.vocab_id
            WHERE s.id = ?
            """,
            (sentence_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["is_favorite"] = bool(item["is_favorite"])
        return item


def get_recent_sentences_for_vocab(
    vocab_id: int,
    limit: int = 8,
    db_path: Path | str | None = None,
) -> list[dict]:
    """Return recent prompts/tags for a vocabulary item to avoid repetition."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, english_prompt, context_tag, structure_tag, level, created_at
            FROM sentences
            WHERE vocab_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (vocab_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def set_sentence_favorite(
    sentence_id: int,
    is_favorite: bool,
    db_path: Path | str | None = None,
) -> bool:
    """Mark or unmark a sentence as a favorite."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE sentences SET is_favorite = ? WHERE id = ?",
            (1 if is_favorite else 0, sentence_id),
        )
        return cursor.rowcount > 0


def list_favorite_sentences(
    search: str = "",
    level: str = "All",
    db_path: Path | str | None = None,
) -> list[dict]:
    """List favorited sentences with vocabulary info and latest attempt details."""
    clauses = ["s.is_favorite = 1"]
    params: list[str] = []

    if level and level != "All":
        clauses.append("s.level = ?")
        params.append(_validate_level(level))

    query = search.strip()
    if query:
        like = f"%{query}%"
        clauses.append(
            "(s.english_prompt LIKE ? OR s.reference_german LIKE ? OR s.context_tag LIKE ? "
            "OR v.german LIKE ? OR v.english LIKE ?)"
        )
        params.extend([like, like, like, like, like])

    where_sql = f"WHERE {' AND '.join(clauses)}"
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                s.id,
                s.vocab_id,
                s.english_prompt,
                s.reference_german,
                s.context_tag,
                s.structure_tag,
                s.level,
                s.is_favorite,
                s.created_at,
                v.german AS vocab_german,
                v.english AS vocab_english,
                v.grammar_info AS vocab_grammar_info
            FROM sentences s
            JOIN vocabulary v ON v.id = s.vocab_id
            {where_sql}
            ORDER BY s.id DESC
            """,
            params,
        ).fetchall()

        results: list[dict] = []
        for row in rows:
            item = dict(row)
            item["is_favorite"] = bool(item["is_favorite"])
            attempt_row = conn.execute(
                """
                SELECT
                    id, sentence_id, user_translation, verdict,
                    grammar_correct, semantic_accurate, grammar_summary, semantic_summary,
                    score, corrected_german, grammar_feedback, word_order_feedback,
                    natural_expressions, alternatives_json, created_at
                FROM attempts
                WHERE sentence_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (item["id"],),
            ).fetchone()
            item["latest_attempt"] = _decode_attempt(attempt_row) if attempt_row else None
            results.append(item)
        return results


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------

def save_attempt(
    sentence_id: int,
    user_translation: str,
    verdict: str,
    grammar_correct: bool,
    semantic_accurate: bool,
    grammar_summary: str,
    semantic_summary: str,
    score: int,
    corrected_german: str,
    grammar_feedback: str = "",
    word_order_feedback: str = "",
    natural_expressions: str = "",
    alternatives: list[str] | None = None,
    db_path: Path | str | None = None,
) -> int:
    """Persist a user translation attempt and structured AI evaluation."""
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"Verdict must be one of {VALID_VERDICTS}, got {verdict!r}")
    bounded_score = max(0, min(100, int(score)))
    alts_json = json.dumps(alternatives or [], ensure_ascii=False)

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO attempts (
                sentence_id, user_translation, verdict,
                grammar_correct, semantic_accurate, grammar_summary, semantic_summary,
                score, corrected_german, grammar_feedback, word_order_feedback,
                natural_expressions, alternatives_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sentence_id,
                user_translation.strip(),
                verdict,
                1 if grammar_correct else 0,
                1 if semantic_accurate else 0,
                grammar_summary.strip(),
                semantic_summary.strip(),
                bounded_score,
                corrected_german.strip(),
                grammar_feedback.strip(),
                word_order_feedback.strip(),
                natural_expressions.strip(),
                alts_json,
            ),
        )
        return int(cursor.lastrowid)


def list_attempts_for_sentence(
    sentence_id: int,
    db_path: Path | str | None = None,
) -> list[dict]:
    """Return all recorded attempts for a sentence, newest first."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id, sentence_id, user_translation, verdict,
                grammar_correct, semantic_accurate, grammar_summary, semantic_summary,
                score, corrected_german, grammar_feedback, word_order_feedback,
                natural_expressions, alternatives_json, created_at
            FROM attempts
            WHERE sentence_id = ?
            ORDER BY id DESC
            """,
            (sentence_id,),
        ).fetchall()
        return [_decode_attempt(row) for row in rows]


def get_latest_attempt_for_sentence(
    sentence_id: int,
    db_path: Path | str | None = None,
) -> dict | None:
    """Return the most recent attempt for a sentence, if any."""
    attempts = list_attempts_for_sentence(sentence_id, db_path=db_path)
    return attempts[0] if attempts else None
