"""Lightweight mobile PWA server for DeutschFlow.

Reuses db.py and ai_service.py directly so the Streamlit web app and the
mobile PWA stay synchronized against the exact same local SQLite database.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import ai_service
import db

PWA_DIR = Path(__file__).resolve().parent / "pwa"


def _get_db_path(request: Request):
    return getattr(request.app.state, "db_path", None)


def _public_sentence(sentence: dict) -> dict:
    """Return sentence fields safe to display BEFORE submission (hides reference_german)."""
    return {
        "id": sentence["id"],
        "vocab_id": sentence["vocab_id"],
        "english_prompt": sentence["english_prompt"],
        "context_tag": sentence["context_tag"],
        "structure_tag": sentence["structure_tag"],
        "level": sentence["level"],
        "is_favorite": bool(sentence["is_favorite"]),
        "created_at": sentence["created_at"],
        "vocab_german": sentence["vocab_german"],
        "vocab_english": sentence["vocab_english"],
        "vocab_grammar_info": sentence["vocab_grammar_info"],
    }


async def _parse_json(request: Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

async def api_health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "app": "DeutschFlow PWA"})


async def api_list_vocab(request: Request) -> JSONResponse:
    search = request.query_params.get("search", "")
    level = request.query_params.get("level", "All")
    db_path = _get_db_path(request)
    try:
        items = await run_in_threadpool(db.list_vocabulary, search, level, db_path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"items": items})


async def api_create_vocab(request: Request) -> JSONResponse:
    data = await _parse_json(request)
    db_path = _get_db_path(request)
    try:
        vocab_id = await run_in_threadpool(
            db.add_vocabulary,
            str(data.get("german", "")),
            str(data.get("english", "")),
            str(data.get("grammar_info", "")),
            str(data.get("level", "B1")),
            str(data.get("notes", "")),
            db_path,
        )
        item = await run_in_threadpool(db.get_vocabulary, vocab_id, db_path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"item": item}, status_code=201)


async def api_update_vocab(request: Request) -> JSONResponse:
    vocab_id = int(request.path_params["vocab_id"])
    data = await _parse_json(request)
    db_path = _get_db_path(request)
    try:
        updated = await run_in_threadpool(
            db.update_vocabulary,
            vocab_id,
            str(data.get("german", "")),
            str(data.get("english", "")),
            str(data.get("grammar_info", "")),
            str(data.get("level", "B1")),
            str(data.get("notes", "")),
            db_path,
        )
        if not updated:
            return JSONResponse({"error": "Vocabulary item not found."}, status_code=404)
        item = await run_in_threadpool(db.get_vocabulary, vocab_id, db_path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"item": item})


async def api_delete_vocab(request: Request) -> JSONResponse:
    vocab_id = int(request.path_params["vocab_id"])
    db_path = _get_db_path(request)
    deleted = await run_in_threadpool(db.delete_vocabulary, vocab_id, db_path)
    if not deleted:
        return JSONResponse({"error": "Vocabulary item not found."}, status_code=404)
    return JSONResponse({"deleted": True})


async def api_generate_challenge(request: Request) -> JSONResponse:
    data = await _parse_json(request)
    db_path = _get_db_path(request)
    try:
        vocab_id = int(data["vocab_id"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "Valid vocab_id is required."}, status_code=400)

    vocab = await run_in_threadpool(db.get_vocabulary, vocab_id, db_path)
    if not vocab:
        return JSONResponse({"error": "Vocabulary item not found."}, status_code=404)

    recent = await run_in_threadpool(db.get_recent_sentences_for_vocab, vocab_id, 8, db_path)

    def _generate():
        service = ai_service.get_ai_service()
        return service.generate_challenge(
            german_expression=vocab["german"],
            english_meaning=vocab["english"],
            grammar_info=vocab["grammar_info"],
            level=vocab["level"],
            recent_sentences=recent,
        )

    try:
        challenge = await run_in_threadpool(_generate)
    except ai_service.AIServiceError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)

    sentence_id = await run_in_threadpool(
        db.create_sentence,
        vocab["id"],
        challenge.english_prompt,
        challenge.reference_german,
        vocab["level"],
        challenge.context_tag,
        challenge.structure_tag,
        db_path,
    )
    sentence = await run_in_threadpool(db.get_sentence, sentence_id, db_path)
    return JSONResponse({"sentence": _public_sentence(sentence)}, status_code=201)


async def api_get_sentence(request: Request) -> JSONResponse:
    sentence_id = int(request.path_params["sentence_id"])
    db_path = _get_db_path(request)
    sentence = await run_in_threadpool(db.get_sentence, sentence_id, db_path)
    if not sentence:
        return JSONResponse({"error": "Sentence not found."}, status_code=404)
    return JSONResponse({"sentence": _public_sentence(sentence)})


async def api_submit_translation(request: Request) -> JSONResponse:
    data = await _parse_json(request)
    db_path = _get_db_path(request)
    try:
        sentence_id = int(data["sentence_id"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "Valid sentence_id is required."}, status_code=400)

    user_translation = str(data.get("user_translation", "")).strip()
    if not user_translation:
        return JSONResponse({"error": "Please enter a German translation."}, status_code=400)

    sentence = await run_in_threadpool(db.get_sentence, sentence_id, db_path)
    if not sentence:
        return JSONResponse({"error": "Sentence not found."}, status_code=404)

    def _evaluate():
        service = ai_service.get_ai_service()
        result = service.evaluate_translation(
            english_prompt=sentence["english_prompt"],
            user_translation=user_translation,
            target_german=sentence["vocab_german"],
            target_english=sentence["vocab_english"],
            target_grammar_info=sentence["vocab_grammar_info"],
            reference_german=sentence["reference_german"],
            level=sentence["level"],
        )
        return result, service.last_provider_used

    try:
        result, provider_used = await run_in_threadpool(_evaluate)
    except ai_service.AIServiceError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)

    attempt_id = await run_in_threadpool(
        db.save_attempt,
        sentence_id,
        user_translation,
        result.verdict,
        result.grammar_correct,
        result.semantic_accurate,
        result.grammar_summary,
        result.semantic_summary,
        result.score,
        result.corrected_german,
        result.grammar_feedback,
        result.word_order_feedback,
        result.natural_expressions,
        result.alternatives,
        db_path,
    )

    return JSONResponse(
        {
            "attempt_id": attempt_id,
            "is_favorite": bool(sentence["is_favorite"]),
            "reference_german": sentence["reference_german"],
            "provider_used": provider_used,
            "evaluation": {
                "verdict": result.verdict,
                "grammar_correct": result.grammar_correct,
                "semantic_accurate": result.semantic_accurate,
                "grammar_summary": result.grammar_summary,
                "semantic_summary": result.semantic_summary,
                "score": result.score,
                "corrected_german": result.corrected_german,
                "grammar_feedback": result.grammar_feedback,
                "word_order_feedback": result.word_order_feedback,
                "natural_expressions": result.natural_expressions,
                "alternatives": result.alternatives,
            },
        }
    )


async def api_toggle_favorite(request: Request) -> JSONResponse:
    sentence_id = int(request.path_params["sentence_id"])
    data = await _parse_json(request)
    db_path = _get_db_path(request)
    is_favorite = bool(data.get("is_favorite", True))
    updated = await run_in_threadpool(db.set_sentence_favorite, sentence_id, is_favorite, db_path)
    if not updated:
        return JSONResponse({"error": "Sentence not found."}, status_code=404)
    return JSONResponse({"sentence_id": sentence_id, "is_favorite": is_favorite})


async def api_list_favorites(request: Request) -> JSONResponse:
    search = request.query_params.get("search", "")
    level = request.query_params.get("level", "All")
    db_path = _get_db_path(request)
    try:
        items = await run_in_threadpool(db.list_favorite_sentences, search, level, db_path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"items": items})


async def api_get_settings(request: Request) -> JSONResponse:
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    return JSONResponse(
        {
            "has_groq": bool(groq_key and groq_key != "your_groq_api_key_here"),
            "has_gemini": bool(gemini_key and gemini_key != "your_gemini_api_key_here"),
            "provider": os.getenv("AI_PROVIDER", ai_service.DEFAULT_AI_PROVIDER),
            "groq_model": os.getenv("GROQ_MODEL", ai_service.DEFAULT_GROQ_MODEL),
            "gemini_model": os.getenv("GEMINI_MODEL", ai_service.DEFAULT_GEMINI_MODEL),
        }
    )


async def api_update_settings(request: Request) -> JSONResponse:
    data = await _parse_json(request)
    env_path = getattr(request.app.state, "env_path", None)
    await run_in_threadpool(
        ai_service.save_api_settings,
        str(data.get("gemini_api_key", "")),
        str(data.get("gemini_model", "")) or None,
        groq_api_key=str(data.get("groq_api_key", "")),
        groq_model=str(data.get("groq_model", "")) or None,
        provider=str(data.get("provider", "")) or None,
        env_path=env_path,
    )
    return await api_get_settings(request)


# ---------------------------------------------------------------------------
# PWA static endpoints
# ---------------------------------------------------------------------------

async def serve_index(_request: Request) -> Response:
    return FileResponse(PWA_DIR / "index.html", headers={"Cache-Control": "no-cache"})


async def serve_manifest(_request: Request) -> Response:
    return FileResponse(
        PWA_DIR / "manifest.json",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


async def serve_sw(_request: Request) -> Response:
    return FileResponse(
        PWA_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


def create_app(db_path: Path | str | None = None, env_path: Path | None = None) -> Starlette:
    """Create the Starlette PWA application sharing the local SQLite database."""
    db.init_db(db_path)

    routes = [
        Route("/", serve_index),
        Route("/manifest.json", serve_manifest),
        Route("/sw.js", serve_sw),
        Route("/api/health", api_health, methods=["GET"]),
        Route("/api/vocab", api_list_vocab, methods=["GET"]),
        Route("/api/vocab", api_create_vocab, methods=["POST"]),
        Route("/api/vocab/{vocab_id:int}", api_update_vocab, methods=["PUT"]),
        Route("/api/vocab/{vocab_id:int}", api_delete_vocab, methods=["DELETE"]),
        Route("/api/practice/generate", api_generate_challenge, methods=["POST"]),
        Route("/api/practice/submit", api_submit_translation, methods=["POST"]),
        Route("/api/sentences/{sentence_id:int}", api_get_sentence, methods=["GET"]),
        Route("/api/sentences/{sentence_id:int}/favorite", api_toggle_favorite, methods=["POST"]),
        Route("/api/favorites", api_list_favorites, methods=["GET"]),
        Route("/api/settings", api_get_settings, methods=["GET"]),
        Route("/api/settings", api_update_settings, methods=["POST"]),
        Mount("/static", app=StaticFiles(directory=str(PWA_DIR)), name="static"),
    ]
    app = Starlette(routes=routes)
    app.state.db_path = db_path
    app.state.env_path = env_path
    return app


def _get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT") or os.getenv("PWA_PORT") or "8000")
    lan_ip = _get_lan_ip()
    print(f"\nDeutschFlow PWA running:")
    print(f"  Laptop: http://localhost:{port}")
    print(f"  Phone (same Wi-Fi): http://{lan_ip}:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
