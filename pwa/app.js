"use strict";

const state = {
  tab: "practice",
  vocab: [],
  practiceLevel: "All",
  selectedVocabId: null,
  activeSentence: null,
  lastEvaluation: null,
  lastUserTranslation: "",
  lastReferenceGerman: "",
  vocabSearch: "",
  vocabLevel: "All",
  favSearch: "",
  favLevel: "All",
  favorites: [],
};

const $ = (id) => document.getElementById(id);

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

let toastTimer = null;
function showToast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 2800);
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function switchTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".pill-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  ["practice", "favorites", "vocabulary"].forEach((name) => {
    $(`view-${name}`).classList.toggle("hidden", name !== tab);
    $(`view-${name}`).classList.toggle("active", name === tab);
  });
  if (tab === "favorites") loadFavorites();
  if (tab === "vocabulary") loadVocabulary();
  if (tab === "practice") renderPractice();
}

// ---------------------------------------------------------------------------
// Practice View
// ---------------------------------------------------------------------------

function getFilteredPracticeVocab() {
  if (state.practiceLevel === "All") return state.vocab;
  return state.vocab.filter((v) => v.level === state.practiceLevel);
}

function renderPractice() {
  const emptyEl = $("practice-empty");
  const mainEl = $("practice-main");

  if (!state.vocab.length) {
    emptyEl.classList.remove("hidden");
    mainEl.classList.add("hidden");
    return;
  }

  emptyEl.classList.add("hidden");
  mainEl.classList.remove("hidden");

  const filtered = getFilteredPracticeVocab();
  const select = $("practice-vocab-select");
  if (!filtered.length) {
    select.innerHTML = `<option value="">No words for ${state.practiceLevel}</option>`;
    $("target-vocab-card").innerHTML = `<p class="muted">No vocabulary entries for level ${state.practiceLevel}.</p>`;
    $("btn-generate").disabled = true;
    return;
  }

  $("btn-generate").disabled = false;
  if (!filtered.some((v) => v.id === state.selectedVocabId)) {
    state.selectedVocabId = filtered[0].id;
  }

  select.innerHTML = filtered
    .map((v) => `<option value="${v.id}">${escapeHtml(v.german)} (${v.level})</option>`)
    .join("");
  select.value = String(state.selectedVocabId);

  const selected = filtered.find((v) => v.id === state.selectedVocabId) || filtered[0];
  const grammarHtml = selected.grammar_info
    ? `<div class="meta-line" style="margin-top:6px;">Grammar: ${escapeHtml(selected.grammar_info)}</div>`
    : "";

  $("target-vocab-card").innerHTML = `
    <div>
      <span class="badge">${escapeHtml(selected.level)}</span>
      <span class="list-row-title">${escapeHtml(selected.german)}</span>
    </div>
    <div class="list-row-sub" style="margin-top:6px;">${escapeHtml(selected.english)}</div>
    ${grammarHtml}
  `;

  if (state.activeSentence) {
    $("challenge-section").classList.remove("hidden");
    const s = state.activeSentence;
    const meta = [s.level, s.context_tag, s.structure_tag].filter(Boolean).join(" · ");
    $("prompt-card").innerHTML = `
      <div class="meta-line">${escapeHtml(meta)}</div>
      <p class="prompt-text">${escapeHtml(s.english_prompt)}</p>
    `;
  } else {
    $("challenge-section").classList.add("hidden");
  }

  renderEvaluation();
}

function verdictBadge(verdict) {
  if (verdict === "correct") return `<span class="badge badge-green">Valid Translation</span>`;
  if (verdict === "minor_issues") return `<span class="badge badge-amber">Minor Issues</span>`;
  return `<span class="badge badge-red">Needs Work</span>`;
}

function buildFeedbackHtml(ev, referenceGerman, userTranslation) {
  const gramBadge = ev.grammar_correct
    ? `<span class="badge badge-green">Grammar: Correct</span>`
    : `<span class="badge badge-red">Grammar: Errors found</span>`;
  const semBadge = ev.semantic_accurate
    ? `<span class="badge badge-green">Meaning: Accurate</span>`
    : `<span class="badge badge-amber">Meaning: Check nuance</span>`;

  const alts = [...(ev.alternatives || [])];
  if (referenceGerman && !alts.includes(referenceGerman) && referenceGerman !== ev.corrected_german) {
    alts.push(referenceGerman);
  }

  return `
    ${verdictBadge(ev.verdict)}
    <div class="eval-grid" style="margin-top:10px;">
      <div class="card" style="margin:0;">
        ${gramBadge}
        <p class="small-text" style="margin:8px 0 0;">${escapeHtml(ev.grammar_summary)}</p>
      </div>
      <div class="card" style="margin:0;">
        ${semBadge}
        <p class="small-text" style="margin:8px 0 0;">${escapeHtml(ev.semantic_summary)}</p>
      </div>
    </div>
    <span class="section-label">Your submission</span>
    <p class="small-text muted" style="margin:4px 0 10px;">${escapeHtml(userTranslation)}</p>
    <span class="section-label">Corrected German</span>
    <div class="corrected-box">${escapeHtml(ev.corrected_german)}</div>
    <div class="card">
      <p class="small-text" style="margin:0 0 8px;"><strong>Grammar explanations</strong><br/>${escapeHtml(ev.grammar_feedback || "No grammatical mistakes.")}</p>
      <p class="small-text" style="margin:0 0 8px;"><strong>Word order</strong><br/>${escapeHtml(ev.word_order_feedback || "Word order is natural and correct.")}</p>
      ${ev.natural_expressions ? `<p class="small-text" style="margin:0 0 8px;"><strong>Optional stylistic improvements</strong><br/>${escapeHtml(ev.natural_expressions)}</p>` : ""}
      ${alts.length ? `<p class="small-text" style="margin:0;"><strong>Alternative valid translations</strong></p><ul class="small-text" style="margin:4px 0 0;padding-left:18px;">${alts.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>` : ""}
    </div>
  `;
}

function renderEvaluation() {
  const el = $("evaluation-section");
  if (!state.lastEvaluation || !state.activeSentence) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }

  el.classList.remove("hidden");
  const isFav = Boolean(state.activeSentence.is_favorite);
  el.innerHTML = `
    <div class="eval-header">
      <h2 class="sheet-title" style="margin:0;">Evaluation</h2>
      <button id="btn-toggle-fav" class="btn-soft-pill ${isFav ? "active-fav" : ""}" type="button">
        ${isFav ? "★ Favorited" : "☆ Save to Favorites"}
      </button>
    </div>
    ${buildFeedbackHtml(state.lastEvaluation, state.lastReferenceGerman, state.lastUserTranslation)}
  `;

  $("btn-toggle-fav").addEventListener("click", async () => {
    try {
      const nextFav = !state.activeSentence.is_favorite;
      await api(`/api/sentences/${state.activeSentence.id}/favorite`, {
        method: "POST",
        body: JSON.stringify({ is_favorite: nextFav }),
      });
      state.activeSentence.is_favorite = nextFav;
      renderEvaluation();
      showToast(nextFav ? "Saved to Favorites" : "Removed from Favorites");
    } catch (err) {
      showToast(err.message);
    }
  });
}

async function handleGenerate() {
  if (!state.selectedVocabId) return;
  const btn = $("btn-generate");
  btn.disabled = true;
  btn.textContent = "Generating...";
  try {
    const data = await api("/api/practice/generate", {
      method: "POST",
      body: JSON.stringify({ vocab_id: state.selectedVocabId }),
    });
    state.activeSentence = data.sentence;
    state.lastEvaluation = null;
    state.lastUserTranslation = "";
    state.lastReferenceGerman = "";
    $("translation-input").value = "";
    renderPractice();
  } catch (err) {
    showToast(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate English Challenge";
  }
}

async function handleSubmitTranslation(e) {
  e.preventDefault();
  if (!state.activeSentence) return;
  const text = $("translation-input").value.trim();
  if (!text) {
    showToast("Please write a German translation first.");
    return;
  }
  const btn = $("btn-submit-translation");
  btn.disabled = true;
  btn.textContent = "Checking...";
  try {
    const data = await api("/api/practice/submit", {
      method: "POST",
      body: JSON.stringify({
        sentence_id: state.activeSentence.id,
        user_translation: text,
      }),
    });
    state.lastEvaluation = data.evaluation;
    state.lastUserTranslation = text;
    state.lastReferenceGerman = data.reference_german;
    state.activeSentence.is_favorite = data.is_favorite;
    renderEvaluation();
  } catch (err) {
    showToast(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Check Translation";
  }
}

// ---------------------------------------------------------------------------
// Favorites View
// ---------------------------------------------------------------------------

async function loadFavorites() {
  try {
    const params = new URLSearchParams({
      search: state.favSearch,
      level: state.favLevel,
    });
    const data = await api(`/api/favorites?${params.toString()}`);
    state.favorites = data.items || [];
    renderFavorites();
  } catch (err) {
    showToast(err.message);
  }
}

function renderFavorites() {
  const count = state.favorites.length;
  $("fav-count").textContent = `${count} saved sentence${count === 1 ? "" : "s"}`;
  const listEl = $("favorites-list");

  if (!count) {
    listEl.innerHTML = `<div class="card"><p class="muted" style="margin:0;">No favorited sentences yet.</p></div>`;
    return;
  }

  listEl.innerHTML = state.favorites
    .map((item) => {
      const meta = [item.level, item.context_tag, item.structure_tag].filter(Boolean).join(" · ");
      const attemptHtml = item.latest_attempt
        ? buildFeedbackHtml(item.latest_attempt, item.reference_german, item.latest_attempt.user_translation)
        : `<p class="small-text" style="margin:6px 0 0;"><strong>Reference German:</strong> ${escapeHtml(item.reference_german)}</p>`;

      return `
        <div class="card">
          <div class="meta-line">
            <span class="badge">${escapeHtml(item.vocab_german)}</span>
            ${escapeHtml(meta)}
          </div>
          <p class="prompt-text" style="font-size:1.1rem;margin-top:8px;">${escapeHtml(item.english_prompt)}</p>
          <div class="controls-row" style="margin:12px 0 0;">
            <button class="btn-soft-pill" data-fav-practice="${item.id}" type="button">Practice Again</button>
            <button class="btn-soft-pill" data-fav-remove="${item.id}" type="button">Remove</button>
          </div>
          <details class="drawer">
            <summary>View saved correction &amp; alternatives</summary>
            <div style="margin-top:10px;">${attemptHtml}</div>
          </details>
        </div>
      `;
    })
    .join("");

  listEl.querySelectorAll("[data-fav-practice]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const id = Number(btn.dataset.favPractice);
        const data = await api(`/api/sentences/${id}`);
        state.selectedVocabId = data.sentence.vocab_id;
        state.practiceLevel = "All";
        $("practice-level-filter").value = "All";
        state.activeSentence = data.sentence;
        state.lastEvaluation = null;
        state.lastUserTranslation = "";
        state.lastReferenceGerman = "";
        $("translation-input").value = "";
        switchTab("practice");
      } catch (err) {
        showToast(err.message);
      }
    });
  });

  listEl.querySelectorAll("[data-fav-remove]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        const id = Number(btn.dataset.favRemove);
        await api(`/api/sentences/${id}/favorite`, {
          method: "POST",
          body: JSON.stringify({ is_favorite: false }),
        });
        await loadFavorites();
        showToast("Removed from Favorites");
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Vocabulary View
// ---------------------------------------------------------------------------

async function loadVocabulary() {
  try {
    const params = new URLSearchParams({
      search: state.vocabSearch,
      level: state.vocabLevel,
    });
    const data = await api(`/api/vocab?${params.toString()}`);
    const items = data.items || [];
    if (!state.vocabSearch && state.vocabLevel === "All") {
      state.vocab = items;
    }
    renderVocabularyList(items);
    if (state.tab === "practice") renderPractice();
  } catch (err) {
    showToast(err.message);
  }
}

function renderVocabularyList(items) {
  $("vocab-count").textContent = `${items.length} saved entr${items.length === 1 ? "y" : "ies"}`;
  const listEl = $("vocab-list");

  if (!items.length) {
    listEl.innerHTML = `<div class="list-row"><span class="muted">No vocabulary entries found.</span></div>`;
    return;
  }

  listEl.innerHTML = items
    .map((item) => `
      <div class="list-row">
        <div class="list-row-main">
          <div>
            <span class="badge">${escapeHtml(item.level)}</span>
            <span class="list-row-title">${escapeHtml(item.german)}</span>
          </div>
          <div class="list-row-sub">${escapeHtml(item.english)}</div>
          ${item.grammar_info ? `<div class="meta-line" style="margin-top:3px;">${escapeHtml(item.grammar_info)}</div>` : ""}
        </div>
        <div class="list-row-actions">
          <button class="btn-soft-pill" data-vocab-practice="${item.id}" type="button">Practice</button>
          <button class="btn-soft-pill" data-vocab-edit="${item.id}" type="button">Edit</button>
          <button class="circle-btn small" data-vocab-del="${item.id}" type="button" title="Delete">−</button>
        </div>
      </div>
    `)
    .join("");

  listEl.querySelectorAll("[data-vocab-practice]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.selectedVocabId = Number(btn.dataset.vocabPractice);
      state.practiceLevel = "All";
      $("practice-level-filter").value = "All";
      state.activeSentence = null;
      state.lastEvaluation = null;
      switchTab("practice");
    });
  });

  listEl.querySelectorAll("[data-vocab-edit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = Number(btn.dataset.vocabEdit);
      const item = items.find((x) => x.id === id);
      if (item) openVocabModal(item);
    });
  });

  listEl.querySelectorAll("[data-vocab-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.vocabDel);
      try {
        await api(`/api/vocab/${id}`, { method: "DELETE" });
        if (state.selectedVocabId === id) state.selectedVocabId = null;
        if (state.activeSentence && state.activeSentence.vocab_id === id) {
          state.activeSentence = null;
          state.lastEvaluation = null;
        }
        await refreshAllVocab();
        showToast("Deleted entry");
      } catch (err) {
        showToast(err.message);
      }
    });
  });
}

async function refreshAllVocab() {
  const allData = await api("/api/vocab");
  state.vocab = allData.items || [];
  if (state.tab === "vocabulary") {
    await loadVocabulary();
  } else {
    renderPractice();
  }
}

function openVocabModal(item = null) {
  $("vocab-edit-id").value = item ? String(item.id) : "";
  $("vocab-modal-title").textContent = item ? "Edit Vocabulary" : "Add Vocabulary";
  $("vocab-german").value = item ? item.german : "";
  $("vocab-english").value = item ? item.english : "";
  $("vocab-level").value = item ? item.level : "B1";
  $("vocab-grammar").value = item ? item.grammar_info : "";
  $("vocab-notes").value = item ? item.notes : "";
  $("vocab-modal").classList.remove("hidden");
}

async function handleSaveVocab(e) {
  e.preventDefault();
  const editId = $("vocab-edit-id").value;
  const payload = {
    german: $("vocab-german").value,
    english: $("vocab-english").value,
    level: $("vocab-level").value,
    grammar_info: $("vocab-grammar").value,
    notes: $("vocab-notes").value,
  };
  try {
    if (editId) {
      await api(`/api/vocab/${editId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      showToast("Updated vocabulary");
    } else {
      const created = await api("/api/vocab", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.selectedVocabId = created.item.id;
      showToast("Added vocabulary");
    }
    $("vocab-modal").classList.add("hidden");
    await refreshAllVocab();
  } catch (err) {
    showToast(err.message);
  }
}

// ---------------------------------------------------------------------------
// Settings Modal
// ---------------------------------------------------------------------------

async function openSettingsModal() {
  try {
    const info = await api("/api/settings");
    const active = [info.has_groq ? "Groq" : "", info.has_gemini ? "Gemini" : ""].filter(Boolean).join(" + ") || "None";
    $("settings-summary").textContent = `Configured keys: ${active} · Synced with local deutschflow.db`;
    $("setting-provider").value = info.provider || "groq_first";
    $("setting-groq-model").value = info.groq_model || "openai/gpt-oss-120b";
    $("setting-gemini-model").value = info.gemini_model || "gemini-2.5-flash";
    $("setting-groq-key").value = "";
    $("setting-gemini-key").value = "";
  } catch (err) {
    showToast(err.message);
  }
  $("settings-modal").classList.remove("hidden");
}

async function handleSaveSettings(e) {
  e.preventDefault();
  try {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        provider: $("setting-provider").value,
        groq_api_key: $("setting-groq-key").value,
        groq_model: $("setting-groq-model").value,
        gemini_api_key: $("setting-gemini-key").value,
        gemini_model: $("setting-gemini-model").value,
      }),
    });
    $("settings-modal").classList.add("hidden");
    showToast("Saved settings to .env");
  } catch (err) {
    showToast(err.message);
  }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

function bindChipGroup(containerId, onChange) {
  const wrap = $(containerId);
  wrap.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      wrap.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      onChange(chip.dataset.level);
    });
  });
}

async function init() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  document.querySelectorAll(".pill-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  $("btn-go-vocab").addEventListener("click", () => {
    switchTab("vocabulary");
    openVocabModal();
  });

  $("practice-level-filter").addEventListener("change", (e) => {
    state.practiceLevel = e.target.value;
    renderPractice();
  });

  $("practice-vocab-select").addEventListener("change", (e) => {
    state.selectedVocabId = Number(e.target.value);
    renderPractice();
  });

  $("btn-random-vocab").addEventListener("click", () => {
    const filtered = getFilteredPracticeVocab();
    if (!filtered.length) return;
    const pick = filtered[Math.floor(Math.random() * filtered.length)];
    state.selectedVocabId = pick.id;
    renderPractice();
  });

  $("btn-generate").addEventListener("click", handleGenerate);
  $("translation-form").addEventListener("submit", handleSubmitTranslation);

  $("vocab-search").addEventListener("input", (e) => {
    state.vocabSearch = e.target.value;
    loadVocabulary();
  });
  bindChipGroup("vocab-level-chips", (lvl) => {
    state.vocabLevel = lvl;
    loadVocabulary();
  });

  $("fav-search").addEventListener("input", (e) => {
    state.favSearch = e.target.value;
    loadFavorites();
  });
  bindChipGroup("fav-level-chips", (lvl) => {
    state.favLevel = lvl;
    loadFavorites();
  });

  $("btn-fab-add").addEventListener("click", () => openVocabModal());
  $("btn-close-vocab-modal").addEventListener("click", () => $("vocab-modal").classList.add("hidden"));
  $("vocab-form").addEventListener("submit", handleSaveVocab);

  $("btn-settings").addEventListener("click", openSettingsModal);
  $("btn-close-settings").addEventListener("click", () => $("settings-modal").classList.add("hidden"));
  $("settings-form").addEventListener("submit", handleSaveSettings);

  await refreshAllVocab();
}

init();
