"""Isolated AI service layer for DeutschFlow (Groq & Google Gemini).

All LLM-specific imports, prompts, retries, and provider fallback logic live in
this module so UI and database code stay provider-agnostic.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests
from dotenv import load_dotenv, set_key
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
DEFAULT_AI_PROVIDER = os.getenv("AI_PROVIDER", "groq_first")

VALID_PROVIDERS = ("groq_first", "gemini_first", "groq", "gemini")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIServiceError(Exception):
    """Raised when no configured AI provider can complete the request."""


@dataclass(frozen=True)
class GeneratedChallenge:
    """Domain object representing a generated English translation prompt."""

    english_prompt: str
    reference_german: str
    context_tag: str
    structure_tag: str


@dataclass(frozen=True)
class TranslationEvaluation:
    """Domain object representing a strict-but-fair translation evaluation."""

    verdict: Literal["correct", "minor_issues", "needs_work"]
    grammar_correct: bool
    semantic_accurate: bool
    grammar_summary: str
    semantic_summary: str
    score: int
    corrected_german: str
    grammar_feedback: str
    word_order_feedback: str
    natural_expressions: str
    alternatives: list[str]


# ---------------------------------------------------------------------------
# Structured output schemas
# ---------------------------------------------------------------------------

class _ChallengeSchema(BaseModel):
    english_prompt: str = Field(
        description="Natural, idiomatic English sentence for the learner to translate into German."
    )
    reference_german: str = Field(
        description="One natural German translation using the target German expression."
    )
    context_tag: str = Field(
        description="Short 1-3 word situation label (e.g. 'workplace', 'travel', 'friendship')."
    )
    structure_tag: str = Field(
        description="Short 1-4 word grammar structure label (e.g. 'subordinate clause', 'Konjunktiv II')."
    )


class _EvaluationSchema(BaseModel):
    verdict: Literal["correct", "minor_issues", "needs_work"]
    grammar_correct: bool = Field(
        description="True only if the German sentence has no actual grammatical, inflectional, case, preposition, or word-order errors."
    )
    semantic_accurate: bool = Field(
        description="True if the German sentence accurately conveys the meaning of the English prompt."
    )
    grammar_summary: str = Field(
        description="One concise sentence summarizing grammatical correctness."
    )
    semantic_summary: str = Field(
        description="One concise sentence summarizing semantic accuracy and target-expression usage."
    )
    score: int = Field(
        ge=0,
        le=100,
        description="Holistic quality score from 0 to 100 matching verdict.",
    )
    corrected_german: str = Field(
        description="Minimally corrected version of the learner's German sentence preserving their valid structure."
    )
    grammar_feedback: str = Field(
        description="Detailed explanation of actual mistakes in cases, articles, prepositions, conjugation, and agreement. State clearly if there are no grammatical errors."
    )
    word_order_feedback: str = Field(
        description="Explanation of any word order errors (V2, verb-final, Satzklammer, TeKaMoLo, pronoun order) or confirmation that word order is valid."
    )
    natural_expressions: str = Field(
        description="Optional stylistic or idiomatic suggestions, clearly distinguished from actual mistakes."
    )
    alternatives: list[str] = Field(
        description="2 to 3 valid, natural alternative German translations."
    )


# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------

def save_api_settings(
    api_key: str = "",
    model: str | None = None,
    *,
    groq_api_key: str = "",
    groq_model: str | None = None,
    provider: str | None = None,
    env_path: Path | None = None,
) -> Path:
    """Persist AI provider settings to the local .env file and update os.environ."""
    target = env_path or ENV_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.touch()

    updates = {
        "GEMINI_API_KEY": api_key.strip(),
        "GEMINI_MODEL": (model or "").strip(),
        "GROQ_API_KEY": groq_api_key.strip(),
        "GROQ_MODEL": (groq_model or "").strip(),
        "AI_PROVIDER": (provider or "").strip(),
    }
    for env_key, value in updates.items():
        if value:
            set_key(str(target), env_key, value)
            os.environ[env_key] = value

    return target


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_GENERATOR_SYSTEM_PROMPT = """You are an expert German-as-a-foreign-language tutor creating translation challenges for an English-speaking learner.

Your job is to produce ONE natural English sentence that the learner will translate into German, along with one reference German translation.

Rules:
1. The English sentence must sound completely natural and idiomatic—never robotic or textbook-stiff.
2. Place the sentence in a realistic everyday, workplace, travel, social, or cultural situation.
3. Match the requested CEFR level (A2, B1, or B2) in vocabulary and clause complexity.
4. Make sure translating the English sentence naturally invites using the target German word or expression.
5. Vary sentence structures (questions, subordinate clauses with weil/obwohl/dass/wenn, relative clauses, Perfekt/Präteritum, modal verbs, Konjunktiv II, passive, etc.) and avoid repeating recent sentences, contexts, or structures provided to you.
6. Do NOT include the German word or hints inside `english_prompt`.
"""

_EVALUATOR_SYSTEM_PROMPT = """You are a strict but fair native-level German teacher evaluating an English-to-German translation.

Core evaluation principles:
1. Evaluate GRAMMATICAL CORRECTNESS and SEMANTIC ACCURACY separately.
   - `grammar_correct`: Is the German grammatically valid (cases, articles, adjective endings, prepositions, verb conjugation, tense auxiliaries, noun capitalization, word order)?
   - `semantic_accurate`: Does the German accurately convey the full meaning of the English prompt?
2. NEVER compare the learner's answer word-for-word against the reference German translation. The reference translation is only ONE possible rendering.
3. Accept any valid, natural German construction—even if the learner chose different phrasing, synonyms, clause ordering, or register (du/Sie, Perfekt/Präteritum where interchangeable) that fits the English prompt.
4. Clearly distinguish ACTUAL MISTAKES from OPTIONAL STYLISTIC IMPROVEMENTS:
   - Do not mark a valid sentence wrong just because another phrasing sounds slightly more idiomatic.
   - If there are no actual grammatical mistakes, set `grammar_correct = true` and explicitly say there are no grammatical errors before sharing any optional style tips in `natural_expressions`.
5. Explain actual errors concretely and clearly:
   - Cases (Nominativ, Akkusativ, Dativ, Genitiv)
   - Articles & determiners (gender, number, case endings)
   - Prepositions (choice and governed case)
   - Verb conjugation & valence (person, number, tense, separable prefix, reflexive pronoun)
   - Word order (V2 main clause, verb-final subordinate clause, Satzklammer, TeKaMoLo, negation placement)
6. For `corrected_german`, fix ONLY what is actually wrong in the learner's own sentence while preserving their chosen structure whenever possible. If their sentence is already valid, return their sentence (fixing at most punctuation/capitalization if needed).
7. Note whether the target German expression was used naturally; if they conveyed the meaning accurately with another valid expression, still acknowledge semantic accuracy and mention the target expression in `natural_expressions` or `semantic_summary`.
8. Verdict rules:
   - "correct": `grammar_correct` is true AND `semantic_accurate` is true (score 90-100).
   - "minor_issues": mostly accurate with 1-2 small grammar, spelling, or nuance slips (score 60-89).
   - "needs_work": major grammatical errors, broken word order, or clear meaning mismatch (score 0-59).
"""


def _build_challenge_prompt(
    *,
    german_expression: str,
    english_meaning: str,
    grammar_info: str,
    level: str,
    recent_sentences: list[dict] | None,
) -> str:
    recent_lines = []
    for item in (recent_sentences or [])[:8]:
        recent_lines.append(
            f"- [{item.get('context_tag', '')} | {item.get('structure_tag', '')}] "
            f"{item.get('english_prompt', '')}"
        )
    recent_block = "\n".join(recent_lines) if recent_lines else "None yet."

    return (
        f"Target German expression: {german_expression}\n"
        f"English meaning: {english_meaning}\n"
        f"Grammar info: {grammar_info or 'Not specified'}\n"
        f"Target CEFR level: {level}\n\n"
        f"Recent prompts to avoid repeating (use a fresh situation and sentence structure):\n"
        f"{recent_block}\n"
    )


def _build_evaluation_prompt(
    *,
    english_prompt: str,
    user_translation: str,
    target_german: str,
    target_english: str,
    target_grammar_info: str,
    reference_german: str,
    level: str,
) -> str:
    return (
        f"CEFR level: {level}\n"
        f"Target vocabulary expression: {target_german} ({target_english})\n"
        f"Target grammar notes: {target_grammar_info or 'None'}\n\n"
        f"English prompt shown to learner:\n{english_prompt}\n\n"
        f"One possible reference translation (do NOT compare word-for-word):\n{reference_german}\n\n"
        f"Learner's German translation:\n{user_translation}\n"
    )


def _clean_json_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _is_transient_error(exc: Exception) -> bool:
    msg = str(exc).upper()
    return any(code in msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "TIMEOUT"))


# ---------------------------------------------------------------------------
# Provider backends
# ---------------------------------------------------------------------------

class _GeminiBackend:
    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def run_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_cls: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_schema=schema_cls,
                        temperature=temperature,
                    ),
                )
                parsed = getattr(response, "parsed", None)
                if isinstance(parsed, schema_cls):
                    return parsed
                raw_text = getattr(response, "text", None)
                if not raw_text:
                    raise AIServiceError("Gemini returned an empty response.")
                return schema_cls.model_validate_json(_clean_json_text(raw_text))
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and _is_transient_error(exc):
                    time.sleep(0.8 * (attempt + 1))
                    continue
                break
        raise AIServiceError(f"Gemini ({self.model}): {last_exc}") from last_exc


class _GroqBackend:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def run_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_cls: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        schema_json = json.dumps(schema_cls.model_json_schema(), ensure_ascii=False)
        json_system = (
            f"{system_prompt}\n\n"
            "Return ONLY a single valid JSON object matching this JSON Schema (no markdown, no extra text):\n"
            f"{schema_json}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": json_system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(GROQ_CHAT_URL, json=payload, headers=headers, timeout=30)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise AIServiceError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                if resp.status_code >= 400:
                    raise AIServiceError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return schema_cls.model_validate_json(_clean_json_text(content))
            except Exception as exc:
                last_exc = exc
                if attempt < 2 and _is_transient_error(exc):
                    time.sleep(0.7 * (attempt + 1))
                    continue
                break
        raise AIServiceError(f"Groq ({self.model}): {last_exc}") from last_exc


# ---------------------------------------------------------------------------
# Unified AIService with retry + provider fallback
# ---------------------------------------------------------------------------

class AIService:
    """Unified AI service supporting Groq and Google Gemini with automatic fallback."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        groq_api_key: str | None = None,
        groq_model: str | None = None,
        provider: str | None = None,
    ) -> None:
        gemini_key = (api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        groq_key = (groq_api_key or os.getenv("GROQ_API_KEY") or "").strip()

        if gemini_key == "your_gemini_api_key_here":
            gemini_key = ""
        if groq_key == "your_groq_api_key_here":
            groq_key = ""

        self.model = (model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip() or "gemini-2.5-flash"
        self.groq_model = (groq_model or os.getenv("GROQ_MODEL") or DEFAULT_GROQ_MODEL).strip() or "openai/gpt-oss-120b"

        # If caller explicitly passed only a Gemini api_key (e.g. legacy tests), prioritize Gemini unless provider overrides
        if provider:
            chosen_provider = provider.strip().lower()
        elif api_key and not groq_api_key:
            chosen_provider = "gemini_first"
        else:
            chosen_provider = (os.getenv("AI_PROVIDER") or DEFAULT_AI_PROVIDER).strip().lower()

        if chosen_provider not in VALID_PROVIDERS:
            chosen_provider = "groq_first"
        self.provider = chosen_provider

        self._backends: list[tuple[str, object]] = []
        gemini_backend = _GeminiBackend(gemini_key, self.model) if gemini_key else None
        groq_backend = _GroqBackend(groq_key, self.groq_model) if groq_key else None

        if self.provider == "groq":
            if groq_backend:
                self._backends.append(("Groq", groq_backend))
        elif self.provider == "gemini":
            if gemini_backend:
                self._backends.append(("Gemini", gemini_backend))
        elif self.provider == "gemini_first":
            if gemini_backend:
                self._backends.append(("Gemini", gemini_backend))
            if groq_backend:
                self._backends.append(("Groq", groq_backend))
        else:  # groq_first
            if groq_backend:
                self._backends.append(("Groq", groq_backend))
            if gemini_backend:
                self._backends.append(("Gemini", gemini_backend))

        if not self._backends:
            raise AIServiceError(
                "Missing API key. Add GROQ_API_KEY or GEMINI_API_KEY in API Settings or your .env file."
            )
        self.last_provider_used: str = ""

    def _execute(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_cls: type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        errors: list[str] = []
        for name, backend in self._backends:
            try:
                result = backend.run_structured(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema_cls=schema_cls,
                    temperature=temperature,
                )
                self.last_provider_used = f"{name} ({backend.model})"
                return result
            except Exception as exc:
                errors.append(str(exc))
        raise AIServiceError("All configured AI providers failed: " + " | ".join(errors))

    def generate_challenge(
        self,
        *,
        german_expression: str,
        english_meaning: str,
        grammar_info: str,
        level: str,
        recent_sentences: list[dict] | None = None,
    ) -> GeneratedChallenge:
        """Generate a contextual English sentence and hidden reference German translation."""
        user_prompt = _build_challenge_prompt(
            german_expression=german_expression,
            english_meaning=english_meaning,
            grammar_info=grammar_info,
            level=level,
            recent_sentences=recent_sentences,
        )
        parsed = self._execute(
            system_prompt=_GENERATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_cls=_ChallengeSchema,
            temperature=0.9,
        )
        return GeneratedChallenge(
            english_prompt=parsed.english_prompt.strip(),
            reference_german=parsed.reference_german.strip(),
            context_tag=parsed.context_tag.strip(),
            structure_tag=parsed.structure_tag.strip(),
        )

    def evaluate_translation(
        self,
        *,
        english_prompt: str,
        user_translation: str,
        target_german: str,
        target_english: str,
        target_grammar_info: str,
        reference_german: str,
        level: str,
    ) -> TranslationEvaluation:
        """Evaluate a learner's German translation strictly but fairly."""
        user_prompt = _build_evaluation_prompt(
            english_prompt=english_prompt,
            user_translation=user_translation,
            target_german=target_german,
            target_english=target_english,
            target_grammar_info=target_grammar_info,
            reference_german=reference_german,
            level=level,
        )
        parsed = self._execute(
            system_prompt=_EVALUATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_cls=_EvaluationSchema,
            temperature=0.2,
        )
        return TranslationEvaluation(
            verdict=parsed.verdict,
            grammar_correct=parsed.grammar_correct,
            semantic_accurate=parsed.semantic_accurate,
            grammar_summary=parsed.grammar_summary.strip(),
            semantic_summary=parsed.semantic_summary.strip(),
            score=max(0, min(100, int(parsed.score))),
            corrected_german=parsed.corrected_german.strip(),
            grammar_feedback=parsed.grammar_feedback.strip(),
            word_order_feedback=parsed.word_order_feedback.strip(),
            natural_expressions=parsed.natural_expressions.strip(),
            alternatives=[alt.strip() for alt in parsed.alternatives if alt.strip()],
        )


def get_ai_service(
    api_key: str | None = None,
    model: str | None = None,
    *,
    groq_api_key: str | None = None,
    groq_model: str | None = None,
    provider: str | None = None,
) -> AIService:
    """Factory returning the configured AI service implementation."""
    return AIService(
        api_key=api_key,
        model=model,
        groq_api_key=groq_api_key,
        groq_model=groq_model,
        provider=provider,
    )
