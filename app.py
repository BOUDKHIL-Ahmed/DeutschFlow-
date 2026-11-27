"""DeutschFlow — Minimalist personal German translation trainer."""

from __future__ import annotations

import html
import os
import random

import streamlit as st

from ai_service import (
    AIServiceError,
    DEFAULT_AI_PROVIDER,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROQ_MODEL,
    ENV_PATH,
    get_ai_service,
    save_api_settings,
)
from db import (
    VALID_LEVELS,
    add_vocabulary,
    create_sentence,
    delete_vocabulary,
    get_recent_sentences_for_vocab,
    get_sentence,
    get_vocabulary,
    init_db,
    list_favorite_sentences,
    list_vocabulary,
    save_attempt,
    set_sentence_favorite,
    update_vocabulary,
)

# ---------------------------------------------------------------------------
# Page setup & minimalist dark styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="DeutschFlow",
    page_icon="🇩🇪",
    layout="centered",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
    --df-bg: #F3EFE6;
    --df-surface: #FAF7F0;
    --df-surface-muted: #EAE4D7;
    --df-border: #E2DCCE;
    --df-border-strong: #D3CCB9;
    --df-text: #1F241E;
    --df-text-secondary: #787368;
    --df-accent: #2F3E2E;
    --df-accent-hover: #3B4D39;
    --df-sans: "Inter", -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Segoe UI", sans-serif;
}

html, body, [data-testid="stAppViewContainer"], .stApp {
    background-color: var(--df-bg) !important;
    color: var(--df-text) !important;
    font-family: var(--df-sans) !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

#MainMenu, footer {
    visibility: hidden;
}

[data-testid="stHeader"] {
    background: transparent !important;
}

.block-container {
    max-width: 700px;
    padding-top: 1.5rem;
    padding-bottom: 3.5rem;
}

.df-title {
    font-family: var(--df-sans) !important;
    font-size: 1.85rem;
    font-weight: 700;
    letter-spacing: -0.025em;
    color: var(--df-text);
    margin: 0;
    line-height: 1.15;
}

.df-subtitle {
    font-family: var(--df-sans);
    font-size: 0.9rem;
    color: var(--df-text-secondary);
    margin: 0.2rem 0 1.2rem 0;
}

.df-card {
    background: var(--df-surface);
    border: 1px solid var(--df-border);
    border-radius: 22px;
    padding: 1.15rem 1.35rem;
    margin: 0.75rem 0;
    box-shadow: 0 2px 10px rgba(47, 62, 46, 0.04);
}

.df-prompt-card {
    background: var(--df-surface);
    border: 1px solid var(--df-border);
    border-radius: 24px;
    padding: 1.45rem 1.6rem;
    margin: 0.95rem 0 1.1rem 0;
    box-shadow: 0 4px 18px rgba(47, 62, 46, 0.06);
}

.df-prompt-text {
    font-family: var(--df-sans);
    font-size: 1.35rem;
    line-height: 1.5;
    font-weight: 500;
    color: var(--df-text);
    margin: 0.5rem 0 0 0;
    letter-spacing: -0.012em;
}

.df-meta {
    font-size: 0.8rem;
    color: var(--df-text-secondary);
    font-weight: 500;
}

.df-badge {
    display: inline-block;
    padding: 0.22rem 0.72rem;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--df-accent);
    color: #FAF7F0;
    border: 1px solid var(--df-accent);
    margin-right: 0.4rem;
}

.df-badge-green {
    background: #E2EFE2;
    color: #244D29;
    border-color: #C3D9C4;
}

.df-badge-amber {
    background: #F6ECD6;
    color: #785012;
    border-color: #E3CE9E;
}

.df-badge-red {
    background: #F4E0DE;
    color: #842B25;
    border-color: #DFBCB8;
}

.df-vocab-target {
    font-size: 1.06rem;
    font-weight: 600;
    color: var(--df-text);
    letter-spacing: -0.01em;
}

.df-vocab-meaning {
    color: var(--df-text-secondary);
    font-size: 0.92rem;
    line-height: 1.45;
}

.df-corrected {
    background: var(--df-surface);
    border: 1px solid var(--df-border-strong);
    border-radius: 18px;
    padding: 1rem 1.2rem;
    font-size: 1.12rem;
    line-height: 1.48;
    font-weight: 500;
    color: var(--df-text);
    margin: 0.4rem 0 0.95rem 0;
}

.df-section-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--df-text-secondary);
    margin-bottom: 0.25rem;
}

/* Pill-shaped Segmented Navigation (matching reference switcher) */
[data-testid="stSegmentedControl"] > div {
    background: var(--df-surface-muted) !important;
    border: none !important;
    border-radius: 999px !important;
    padding: 4px !important;
}

[data-testid="stSegmentedControl"] button {
    border-radius: 999px !important;
    font-family: var(--df-sans) !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    color: var(--df-text-secondary) !important;
    border: none !important;
    transition: all 0.16s ease !important;
}

[data-testid="stSegmentedControl"] button[aria-checked="true"],
[data-testid="stSegmentedControl"] button[data-selected="true"] {
    background: var(--df-accent) !important;
    color: #FFFFFF !important;
}

/* Pill buttons matching reference UI */
div.stButton > button,
div.stFormSubmitButton > button {
    border-radius: 999px !important;
    font-family: var(--df-sans) !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    padding: 0.5rem 1.15rem !important;
    transition: transform 0.12s ease, background-color 0.16s ease, box-shadow 0.16s ease !important;
}

div.stButton > button[kind="primary"],
div.stFormSubmitButton > button[kind="primary"] {
    background-color: var(--df-accent) !important;
    border: 1px solid var(--df-accent) !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 12px rgba(47, 62, 46, 0.18) !important;
}

div.stButton > button[kind="primary"]:hover,
div.stFormSubmitButton > button[kind="primary"]:hover {
    background-color: var(--df-accent-hover) !important;
    border-color: var(--df-accent-hover) !important;
}

div.stButton > button[kind="secondary"],
div.stFormSubmitButton > button[kind="secondary"] {
    background-color: var(--df-surface) !important;
    border: 1px solid var(--df-border) !important;
    color: var(--df-text) !important;
}

div.stButton > button[kind="secondary"]:hover,
div.stFormSubmitButton > button[kind="secondary"]:hover {
    background-color: var(--df-surface-muted) !important;
}

div.stButton > button:active,
div.stFormSubmitButton > button:active {
    transform: scale(0.985);
}

/* Pill inputs, rounded textareas & dropdowns */
[data-testid="stTextInput"] input {
    background-color: var(--df-surface) !important;
    border: 1px solid var(--df-border) !important;
    border-radius: 999px !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    color: var(--df-text) !important;
    font-family: var(--df-sans) !important;
}

[data-baseweb="select"] > div {
    background-color: var(--df-surface) !important;
    border: 1px solid var(--df-border) !important;
    border-radius: 999px !important;
    color: var(--df-text) !important;
    font-family: var(--df-sans) !important;
}

[data-testid="stTextArea"] textarea {
    background-color: var(--df-surface) !important;
    border: 1px solid var(--df-border) !important;
    border-radius: 20px !important;
    padding: 0.9rem 1.05rem !important;
    color: var(--df-text) !important;
    font-family: var(--df-sans) !important;
}

[data-testid="stTextArea"] textarea:focus,
[data-testid="stTextInput"] input:focus {
    border-color: var(--df-accent) !important;
    box-shadow: 0 0 0 2px rgba(47, 62, 46, 0.14) !important;
}

[data-testid="stExpander"] {
    background-color: var(--df-surface) !important;
    border: 1px solid var(--df-border) !important;
    border-radius: 20px !important;
    overflow: hidden;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 20px !important;
    border-color: var(--df-border) !important;
    background-color: var(--df-surface) !important;
}

[data-testid="stForm"] {
    border-radius: 22px !important;
    border-color: var(--df-border) !important;
    background-color: var(--df-surface) !important;
}

hr {
    border-color: var(--df-border) !important;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers & session state
# ---------------------------------------------------------------------------

def _init_session_state() -> None:
    defaults = {
        "nav_page": "Practice",
        "pending_nav": None,
        "selected_vocab_id": None,
        "pending_vocab_id": None,
        "active_sentence_id": None,
        "latest_evaluation": None,
        "latest_user_translation": "",
        "practice_nonce": 0,
        "editing_vocab_id": None,
        "session_api_key": "",
        "session_model": DEFAULT_GEMINI_MODEL,
        "session_groq_key": "",
        "session_groq_model": DEFAULT_GROQ_MODEL,
        "session_provider": DEFAULT_AI_PROVIDER,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _apply_pending_navigation() -> None:
    if st.session_state["pending_nav"]:
        st.session_state["nav_page"] = st.session_state["pending_nav"]
        st.session_state["pending_nav"] = None
    if st.session_state["pending_vocab_id"] is not None:
        st.session_state["selected_vocab_id"] = st.session_state["pending_vocab_id"]
        st.session_state["pending_vocab_id"] = None


def _resolve_gemini_key() -> str:
    placeholder = "your_gemini_api_key_here"
    session_key = (st.session_state.get("session_api_key") or "").strip()
    if session_key and session_key != placeholder:
        return session_key
    env_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if env_key and env_key != placeholder:
        return env_key
    try:
        secret_key = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
        return "" if secret_key == placeholder else secret_key
    except Exception:
        return ""


def _resolve_groq_key() -> str:
    placeholder = "your_groq_api_key_here"
    session_key = (st.session_state.get("session_groq_key") or "").strip()
    if session_key and session_key != placeholder:
        return session_key
    env_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if env_key and env_key != placeholder:
        return env_key
    try:
        secret_key = str(st.secrets.get("GROQ_API_KEY", "")).strip()
        return "" if secret_key == placeholder else secret_key
    except Exception:
        return ""


def _build_ai_service():
    return get_ai_service(
        api_key=_resolve_gemini_key(),
        model=st.session_state["session_model"],
        groq_api_key=_resolve_groq_key(),
        groq_model=st.session_state["session_groq_model"],
        provider=st.session_state["session_provider"],
    )


_PROVIDER_LABELS = {
    "groq_first": "Groq primary, Gemini backup (Fastest)",
    "gemini_first": "Gemini primary, Groq backup",
    "groq": "Groq only",
    "gemini": "Gemini only",
}


def _render_api_status_if_needed() -> None:
    gemini_key = _resolve_gemini_key()
    groq_key = _resolve_groq_key()
    has_any_key = bool(gemini_key or groq_key)
    label = "API Settings" if has_any_key else "API Settings (API key required)"

    with st.expander(label, expanded=not has_any_key):
        if has_any_key:
            active_parts = []
            if groq_key:
                active_parts.append("Groq")
            if gemini_key:
                active_parts.append("Gemini")
            st.caption(
                f"Configured: **{' + '.join(active_parts)}** (loaded from `{ENV_PATH.name}` / environment)."
            )
        else:
            st.caption(
                f"Enter a Groq or Gemini API key below and click **Save Settings Locally** so it persists in `{ENV_PATH.name}`."
            )

        provider_options = list(_PROVIDER_LABELS.keys())
        current_provider = st.session_state["session_provider"]
        if current_provider not in provider_options:
            current_provider = "groq_first"

        with st.form("api_settings_form"):
            selected_provider = st.selectbox(
                "AI Provider Mode",
                options=provider_options,
                index=provider_options.index(current_provider),
                format_func=lambda p: _PROVIDER_LABELS[p],
            )
            c_groq1, c_groq2 = st.columns([1.4, 1])
            with c_groq1:
                groq_key_input = st.text_input(
                    "Groq API Key",
                    value=st.session_state["session_groq_key"],
                    type="password",
                    placeholder="gsk_... (saved in .env)" if groq_key else "gsk_...",
                )
            with c_groq2:
                groq_model_input = st.text_input(
                    "Groq Model",
                    value=st.session_state["session_groq_model"],
                    help="e.g. openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.8-27b",
                )

            c_gem1, c_gem2 = st.columns([1.4, 1])
            with c_gem1:
                key_input = st.text_input(
                    "Gemini API Key (optional backup)",
                    value=st.session_state["session_api_key"],
                    type="password",
                    placeholder="AIza... (saved in .env)" if gemini_key else "AIza...",
                )
            with c_gem2:
                model_input = st.text_input(
                    "Gemini Model",
                    value=st.session_state["session_model"],
                )

            c1, c2 = st.columns(2)
            with c1:
                save_local = st.form_submit_button("Save Settings Locally", type="primary", use_container_width=True)
            with c2:
                use_session = st.form_submit_button("Use for This Session Only", use_container_width=True)

        if save_local:
            eff_gemini_key = key_input.strip() or gemini_key
            eff_gemini_model = model_input.strip() or DEFAULT_GEMINI_MODEL
            eff_groq_key = groq_key_input.strip() or groq_key
            eff_groq_model = groq_model_input.strip() or DEFAULT_GROQ_MODEL
            if not eff_gemini_key and not eff_groq_key:
                st.warning("Please enter at least one API key (Groq or Gemini) to save.")
            else:
                save_api_settings(
                    api_key=eff_gemini_key,
                    model=eff_gemini_model,
                    groq_api_key=eff_groq_key,
                    groq_model=eff_groq_model,
                    provider=selected_provider,
                )
                st.session_state["session_api_key"] = ""
                st.session_state["session_groq_key"] = ""
                st.session_state["session_model"] = eff_gemini_model
                st.session_state["session_groq_model"] = eff_groq_model
                st.session_state["session_provider"] = selected_provider
                st.success(f"Saved locally to `{ENV_PATH.name}`.")
                st.rerun()

        if use_session:
            if key_input.strip():
                st.session_state["session_api_key"] = key_input.strip()
            if groq_key_input.strip():
                st.session_state["session_groq_key"] = groq_key_input.strip()
            if model_input.strip():
                st.session_state["session_model"] = model_input.strip()
            if groq_model_input.strip():
                st.session_state["session_groq_model"] = groq_model_input.strip()
            st.session_state["session_provider"] = selected_provider
            st.rerun()


def _verdict_badge(verdict: str) -> str:
    if verdict == "correct":
        return '<span class="df-badge df-badge-green">Valid Translation</span>'
    if verdict == "minor_issues":
        return '<span class="df-badge df-badge-amber">Minor Issues</span>'
    return '<span class="df-badge df-badge-red">Needs Work</span>'


def _render_feedback_block(
    *,
    evaluation: dict,
    reference_german: str,
    user_translation: str,
) -> None:
    """Render structured AI evaluation with separate grammar & semantic status."""
    verdict_html = _verdict_badge(evaluation["verdict"])
    st.markdown(verdict_html, unsafe_allow_html=True)

    col_gram, col_sem = st.columns(2)
    with col_gram:
        gram_ok = bool(evaluation["grammar_correct"])
        gram_badge = (
            '<span class="df-badge df-badge-green">Grammar: Correct</span>'
            if gram_ok
            else '<span class="df-badge df-badge-red">Grammar: Errors found</span>'
        )
        st.markdown(
            f'<div class="df-card">{gram_badge}<div style="margin-top:0.55rem;color:#55524A;font-size:0.93rem;line-height:1.45;">'
            f'{html.escape(evaluation["grammar_summary"])}</div></div>',
            unsafe_allow_html=True,
        )
    with col_sem:
        sem_ok = bool(evaluation["semantic_accurate"])
        sem_badge = (
            '<span class="df-badge df-badge-green">Meaning: Accurate</span>'
            if sem_ok
            else '<span class="df-badge df-badge-amber">Meaning: Check nuance</span>'
        )
        st.markdown(
            f'<div class="df-card">{sem_badge}<div style="margin-top:0.55rem;color:#55524A;font-size:0.93rem;line-height:1.45;">'
            f'{html.escape(evaluation["semantic_summary"])}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="df-section-label">Your submission</div>', unsafe_allow_html=True)
    st.caption(user_translation)

    st.markdown('<div class="df-section-label">Corrected German</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="df-corrected">{html.escape(evaluation["corrected_german"])}</div>',
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown("**Grammar explanations**")
        st.write(evaluation["grammar_feedback"] or "No grammatical mistakes.")

        st.markdown("**Word order**")
        st.write(evaluation["word_order_feedback"] or "Word order is natural and correct.")

        if evaluation.get("natural_expressions"):
            st.markdown("**Optional stylistic improvements**")
            st.write(evaluation["natural_expressions"])

        alternatives: list[str] = list(evaluation.get("alternatives") or [])
        if reference_german and reference_german not in alternatives and reference_german != evaluation["corrected_german"]:
            alternatives.append(reference_german)

        if alternatives:
            st.markdown("**Alternative valid translations**")
            for alt in alternatives:
                st.markdown(f"- {alt}")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def render_practice_view() -> None:
    vocab_items = list_vocabulary()
    if not vocab_items:
        st.info("Your vocabulary collection is empty. Add a few German words or expressions first.")
        if st.button("Go to Vocabulary", type="primary"):
            st.session_state["pending_nav"] = "Vocabulary"
            st.rerun()
        return

    # Selection bar
    col_filter, col_select, col_rand = st.columns([1.1, 3.2, 1.0])
    with col_filter:
        level_filter = st.selectbox("Level", ["All", *VALID_LEVELS], key="practice_level_filter")

    filtered_vocab = [
        item for item in vocab_items if level_filter == "All" or item["level"] == level_filter
    ]
    if not filtered_vocab:
        st.warning(f"No vocabulary items found for level {level_filter}.")
        return

    vocab_by_id = {item["id"]: item for item in filtered_vocab}
    option_ids = list(vocab_by_id.keys())

    current_vocab_id = st.session_state.get("selected_vocab_id")
    if current_vocab_id not in vocab_by_id:
        current_vocab_id = option_ids[0]
        st.session_state["selected_vocab_id"] = current_vocab_id

    with col_select:
        selected_id = st.selectbox(
            "Target expression",
            options=option_ids,
            index=option_ids.index(current_vocab_id),
            format_func=lambda vid: f"{vocab_by_id[vid]['german']} ({vocab_by_id[vid]['level']})",
            key="practice_vocab_select",
        )
        st.session_state["selected_vocab_id"] = selected_id

    with col_rand:
        st.write("")
        st.write("")
        if st.button("Random", use_container_width=True, help="Pick a random vocabulary item"):
            chosen = random.choice(option_ids)
            st.session_state["pending_vocab_id"] = chosen
            st.rerun()

    selected_vocab = vocab_by_id[selected_id]

    # Target vocabulary card (visible by default per user preference)
    grammar_line = (
        f'<div class="df-meta" style="margin-top:0.35rem;">Grammar: {html.escape(selected_vocab["grammar_info"])}</div>'
        if selected_vocab["grammar_info"]
        else ""
    )
    st.markdown(
        f"""
        <div class="df-card">
            <div>
                <span class="df-badge">{html.escape(selected_vocab["level"])}</span>
                <span class="df-vocab-target">{html.escape(selected_vocab["german"])}</span>
            </div>
            <div class="df-vocab-meaning" style="margin-top:0.3rem;">
                {html.escape(selected_vocab["english"])}
            </div>
            {grammar_line}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Generate English Challenge", type="primary", use_container_width=True):
        try:
            ai = _build_ai_service()
            recent = get_recent_sentences_for_vocab(selected_vocab["id"], limit=8)
            with st.spinner("Generating natural English sentence..."):
                challenge = ai.generate_challenge(
                    german_expression=selected_vocab["german"],
                    english_meaning=selected_vocab["english"],
                    grammar_info=selected_vocab["grammar_info"],
                    level=selected_vocab["level"],
                    recent_sentences=recent,
                )
            sentence_id = create_sentence(
                vocab_id=selected_vocab["id"],
                english_prompt=challenge.english_prompt,
                reference_german=challenge.reference_german,
                level=selected_vocab["level"],
                context_tag=challenge.context_tag,
                structure_tag=challenge.structure_tag,
            )
            st.session_state["active_sentence_id"] = sentence_id
            st.session_state["latest_evaluation"] = None
            st.session_state["latest_user_translation"] = ""
            st.session_state["practice_nonce"] += 1
            st.rerun()
        except AIServiceError as exc:
            st.error(str(exc))

    # Active sentence challenge
    active_sentence_id = st.session_state.get("active_sentence_id")
    if not active_sentence_id:
        st.caption("Click **Generate English Challenge** to start translating.")
        return

    sentence = get_sentence(active_sentence_id)
    if not sentence:
        st.session_state["active_sentence_id"] = None
        return

    meta_parts = [sentence["level"]]
    if sentence["context_tag"]:
        meta_parts.append(sentence["context_tag"])
    if sentence["structure_tag"]:
        meta_parts.append(sentence["structure_tag"])
    if sentence["vocab_id"] != selected_vocab["id"]:
        meta_parts.append(f"Target: {sentence['vocab_german']}")

    st.markdown(
        f"""
        <div class="df-prompt-card">
            <div class="df-meta">{html.escape(" · ".join(meta_parts))}</div>
            <p class="df-prompt-text">{html.escape(sentence["english_prompt"])}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    input_key = f"translation_input_{sentence['id']}_{st.session_state['practice_nonce']}"
    with st.form(key=f"translation_form_{sentence['id']}_{st.session_state['practice_nonce']}"):
        user_translation = st.text_area(
            "Your German translation",
            height=115,
            placeholder="Write your German translation here...",
            key=input_key,
        )
        submitted = st.form_submit_button("Check Translation", type="primary", use_container_width=True)

    if submitted:
        cleaned = user_translation.strip()
        if not cleaned:
            st.warning("Please enter a German translation before submitting.")
        else:
            try:
                ai = _build_ai_service()
                with st.spinner("Evaluating grammar and meaning..."):
                    result = ai.evaluate_translation(
                        english_prompt=sentence["english_prompt"],
                        user_translation=cleaned,
                        target_german=sentence["vocab_german"],
                        target_english=sentence["vocab_english"],
                        target_grammar_info=sentence["vocab_grammar_info"],
                        reference_german=sentence["reference_german"],
                        level=sentence["level"],
                    )
                save_attempt(
                    sentence_id=sentence["id"],
                    user_translation=cleaned,
                    verdict=result.verdict,
                    grammar_correct=result.grammar_correct,
                    semantic_accurate=result.semantic_accurate,
                    grammar_summary=result.grammar_summary,
                    semantic_summary=result.semantic_summary,
                    score=result.score,
                    corrected_german=result.corrected_german,
                    grammar_feedback=result.grammar_feedback,
                    word_order_feedback=result.word_order_feedback,
                    natural_expressions=result.natural_expressions,
                    alternatives=result.alternatives,
                )
                st.session_state["latest_evaluation"] = {
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
                }
                st.session_state["latest_user_translation"] = cleaned
                st.rerun()
            except AIServiceError as exc:
                st.error(str(exc))

    # Show evaluation + Favorite toggle ONLY after submission
    evaluation = st.session_state.get("latest_evaluation")
    if evaluation:
        st.divider()
        header_col, fav_col = st.columns([3, 1.4])
        with header_col:
            st.subheader("Evaluation")
        with fav_col:
            is_fav = bool(sentence["is_favorite"])
            fav_label = "★ Favorited" if is_fav else "☆ Save to Favorites"
            if st.button(fav_label, key=f"fav_btn_{sentence['id']}", use_container_width=True):
                set_sentence_favorite(sentence["id"], not is_fav)
                st.rerun()

        _render_feedback_block(
            evaluation=evaluation,
            reference_german=sentence["reference_german"],
            user_translation=st.session_state.get("latest_user_translation", ""),
        )


def render_favorites_view() -> None:
    col_search, col_level = st.columns([3, 1])
    with col_search:
        search = st.text_input("Search favorites", placeholder="Search English, German, or context...", key="fav_search")
    with col_level:
        level_filter = st.selectbox("Level", ["All", *VALID_LEVELS], key="fav_level")

    favorites = list_favorite_sentences(search=search, level=level_filter)
    st.caption(f"{len(favorites)} saved sentence{'s' if len(favorites) != 1 else ''}")

    if not favorites:
        st.info("No favorited sentences yet. After checking a translation in Practice, click **Save to Favorites**.")
        return

    for item in favorites:
        meta_parts = [item["level"]]
        if item["context_tag"]:
            meta_parts.append(item["context_tag"])
        if item["structure_tag"]:
            meta_parts.append(item["structure_tag"])

        st.markdown(
            f"""
            <div class="df-prompt-card" style="margin-bottom:0.5rem;">
                <div class="df-meta">
                    <span class="df-badge">{html.escape(item["vocab_german"])}</span>
                    {html.escape(" · ".join(meta_parts))}
                </div>
                <p class="df-prompt-text" style="font-size:1.12rem;">{html.escape(item["english_prompt"])}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        act_col1, act_col2, _ = st.columns([1.3, 1.3, 2.4])
        with act_col1:
            if st.button("Practice Again", key=f"fav_practice_{item['id']}", use_container_width=True):
                st.session_state["pending_vocab_id"] = item["vocab_id"]
                st.session_state["active_sentence_id"] = item["id"]
                st.session_state["latest_evaluation"] = None
                st.session_state["latest_user_translation"] = ""
                st.session_state["practice_nonce"] += 1
                st.session_state["pending_nav"] = "Practice"
                st.rerun()
        with act_col2:
            if st.button("Remove Favorite", key=f"fav_remove_{item['id']}", use_container_width=True):
                set_sentence_favorite(item["id"], False)
                st.rerun()

        latest = item.get("latest_attempt")
        with st.expander("View saved correction & alternatives", expanded=False):
            if latest:
                _render_feedback_block(
                    evaluation=latest,
                    reference_german=item["reference_german"],
                    user_translation=latest["user_translation"],
                )
            else:
                st.markdown("**Reference German**")
                st.write(item["reference_german"])


def render_vocabulary_view() -> None:
    existing_all = list_vocabulary()

    with st.expander("Add new word or expression", expanded=len(existing_all) == 0):
        with st.form("add_vocab_form", clear_on_submit=True):
            c1, c2 = st.columns([2.4, 1])
            with c1:
                german = st.text_input(
                    "German word or expression",
                    placeholder="e.g. sich auf jdn./etw. verlassen",
                )
            with c2:
                level = st.selectbox("Level", VALID_LEVELS, index=1)

            english = st.text_input(
                "English meaning",
                placeholder="e.g. to rely on someone/something",
            )
            grammar_info = st.text_input(
                "Grammatical information",
                placeholder="e.g. reflexive verb + auf (Akk.), inseparable",
            )
            notes = st.text_input(
                "Notes (optional)",
                placeholder="Where you saw it or usage nuance",
            )
            submitted = st.form_submit_button("Add to Vocabulary", type="primary")
            if submitted:
                if not german.strip() or not english.strip():
                    st.warning("Please provide both the German expression and its English meaning.")
                else:
                    new_id = add_vocabulary(
                        german=german,
                        english=english,
                        grammar_info=grammar_info,
                        level=level,
                        notes=notes,
                    )
                    st.session_state["selected_vocab_id"] = new_id
                    st.success(f"Added '{german.strip()}'.")
                    st.rerun()

    st.divider()

    col_search, col_level = st.columns([3, 1])
    with col_search:
        search = st.text_input("Search vocabulary", placeholder="Search German, English, or grammar...", key="vocab_search")
    with col_level:
        level_filter = st.selectbox("Level", ["All", *VALID_LEVELS], key="vocab_level_filter")

    items = list_vocabulary(search=search, level=level_filter)
    st.caption(f"{len(items)} saved entr{'y' if len(items) == 1 else 'ies'}")

    if not items:
        st.info("No vocabulary entries match your filter.")
        return

    editing_id = st.session_state.get("editing_vocab_id")

    for item in items:
        if editing_id == item["id"]:
            with st.container(border=True):
                with st.form(f"edit_vocab_form_{item['id']}"):
                    c1, c2 = st.columns([2.4, 1])
                    with c1:
                        edit_german = st.text_input("German", value=item["german"])
                    with c2:
                        edit_level = st.selectbox(
                            "Level",
                            VALID_LEVELS,
                            index=VALID_LEVELS.index(item["level"]),
                        )
                    edit_english = st.text_input("English meaning", value=item["english"])
                    edit_grammar = st.text_input("Grammatical information", value=item["grammar_info"])
                    edit_notes = st.text_input("Notes", value=item["notes"])

                    save_col, cancel_col = st.columns(2)
                    with save_col:
                        save_clicked = st.form_submit_button("Save Changes", type="primary", use_container_width=True)
                    with cancel_col:
                        cancel_clicked = st.form_submit_button("Cancel", use_container_width=True)

                    if save_clicked:
                        if not edit_german.strip() or not edit_english.strip():
                            st.warning("German expression and English meaning cannot be empty.")
                        else:
                            update_vocabulary(
                                item["id"],
                                german=edit_german,
                                english=edit_english,
                                grammar_info=edit_grammar,
                                level=edit_level,
                                notes=edit_notes,
                            )
                            st.session_state["editing_vocab_id"] = None
                            st.rerun()
                    if cancel_clicked:
                        st.session_state["editing_vocab_id"] = None
                        st.rerun()
            continue

        grammar_html = (
            f'<div class="df-meta" style="margin-top:0.35rem;">{html.escape(item["grammar_info"])}</div>'
            if item["grammar_info"]
            else ""
        )
        notes_html = (
            f'<div class="df-meta" style="margin-top:0.2rem;">Note: {html.escape(item["notes"])}</div>'
            if item["notes"]
            else ""
        )
        st.markdown(
            f"""
            <div class="df-card" style="margin-bottom:0.45rem;">
                <div>
                    <span class="df-badge">{html.escape(item["level"])}</span>
                    <span class="df-vocab-target">{html.escape(item["german"])}</span>
                </div>
                <div class="df-vocab-meaning" style="margin-top:0.28rem;">
                    {html.escape(item["english"])}
                </div>
                {grammar_html}
                {notes_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
        b1, b2, b3, _ = st.columns([1.1, 0.9, 0.9, 2.5])
        with b1:
            if st.button("Practice", key=f"practice_vocab_{item['id']}", use_container_width=True):
                st.session_state["pending_vocab_id"] = item["id"]
                st.session_state["active_sentence_id"] = None
                st.session_state["latest_evaluation"] = None
                st.session_state["pending_nav"] = "Practice"
                st.rerun()
        with b2:
            if st.button("Edit", key=f"edit_vocab_{item['id']}", use_container_width=True):
                st.session_state["editing_vocab_id"] = item["id"]
                st.rerun()
        with b3:
            if st.button("Delete", key=f"del_vocab_{item['id']}", use_container_width=True):
                delete_vocabulary(item["id"])
                if st.session_state.get("selected_vocab_id") == item["id"]:
                    st.session_state["selected_vocab_id"] = None
                if st.session_state.get("active_sentence_id"):
                    if get_sentence(st.session_state["active_sentence_id"]) is None:
                        st.session_state["active_sentence_id"] = None
                        st.session_state["latest_evaluation"] = None
                st.rerun()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    init_db()
    _init_session_state()
    _apply_pending_navigation()

    st.markdown('<h1 class="df-title">DeutschFlow</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="df-subtitle">Personal German translation practice from your saved vocabulary.</p>',
        unsafe_allow_html=True,
    )

    _render_api_status_if_needed()

    nav = st.segmented_control(
        "Navigation",
        options=["Practice", "Favorites", "Vocabulary"],
        key="nav_page",
        label_visibility="collapsed",
    )
    if nav is None:
        nav = "Practice"

    st.write("")

    if nav == "Practice":
        render_practice_view()
    elif nav == "Favorites":
        render_favorites_view()
    else:
        render_vocabulary_view()


if __name__ == "__main__":
    main()
