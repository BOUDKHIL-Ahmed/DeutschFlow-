export const VALID_LEVELS = ["A2", "B1", "B2"] as const;
export type CefrLevel = (typeof VALID_LEVELS)[number];

export const VALID_VERDICTS = ["correct", "minor_issues", "needs_work"] as const;
export type Verdict = (typeof VALID_VERDICTS)[number];

export interface VocabularyItem {
  id: number;
  german: string;
  english: string;
  grammar_info: string;
  level: CefrLevel;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface SentenceItem {
  id: number;
  vocab_id: number;
  english_prompt: string;
  reference_german: string;
  context_tag: string;
  structure_tag: string;
  level: CefrLevel;
  is_favorite: boolean;
  created_at: string;
}

export interface SentenceWithVocab extends SentenceItem {
  vocab_german: string;
  vocab_english: string;
  vocab_grammar_info: string;
  vocab_level: CefrLevel;
}

export interface AttemptItem {
  id: number;
  sentence_id: number;
  user_translation: string;
  verdict: Verdict;
  grammar_correct: boolean;
  semantic_accurate: boolean;
  grammar_summary: string;
  semantic_summary: string;
  score: number;
  corrected_german: string;
  grammar_feedback: string;
  word_order_feedback: string;
  natural_expressions: string;
  alternatives: string[];
  created_at: string;
}

export interface FavoriteSentenceItem extends Omit<SentenceWithVocab, "vocab_level"> {
  latest_attempt: AttemptItem | null;
}

const vocabularyStore = new Map<number, VocabularyItem>();
const sentenceStore = new Map<number, SentenceItem>();
const attemptStore = new Map<number, AttemptItem>();

let nextVocabId = 1;
let nextSentenceId = 1;
let nextAttemptId = 1;
let initialized = false;

function nowIso(): string {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

export function validateLevel(level: string): CefrLevel {
  const normalized = level.trim().toUpperCase();
  if (!VALID_LEVELS.includes(normalized as CefrLevel)) {
    throw new Error(`Level must be one of ${VALID_LEVELS.join(", ")}, got '${level}'`);
  }
  return normalized as CefrLevel;
}

export function initDb(): void {
  if (initialized) return;
  initialized = true;

  // Seed starter vocabulary entries for immediate practice on boot
  addVocabulary(
    "sich freuen auf",
    "to look forward to",
    "reflexive verb + auf (Akk.)",
    "A2",
    "Used for upcoming events"
  );
  addVocabulary(
    "sich auf jdn. verlassen",
    "to rely on someone",
    "reflexive verb + auf (Akk.)",
    "B1",
    "Common in everyday and workplace contexts"
  );
  addVocabulary(
    "es kommt darauf an",
    "it depends",
    "impersonal expression + auf (Akk.)",
    "B2",
    "Often followed by ob / wie / was clause"
  );
}

export function addVocabulary(
  german: string,
  english: string,
  grammarInfo = "",
  level = "B1",
  notes = ""
): number {
  const germanClean = german.trim();
  const englishClean = english.trim();
  if (!germanClean || !englishClean) {
    throw new Error("Both German expression and English meaning are required.");
  }

  const validLevel = validateLevel(level);
  const id = nextVocabId++;
  const timestamp = nowIso();
  vocabularyStore.set(id, {
    id,
    german: germanClean,
    english: englishClean,
    grammar_info: grammarInfo.trim(),
    level: validLevel,
    notes: notes.trim(),
    created_at: timestamp,
    updated_at: timestamp,
  });
  return id;
}

export function listVocabulary(search = "", level = "All"): VocabularyItem[] {
  let validLevel: CefrLevel | null = null;
  if (level && level !== "All") {
    validLevel = validateLevel(level);
  }

  const query = search.trim().toLowerCase();
  const results = Array.from(vocabularyStore.values()).filter((item) => {
    if (validLevel && item.level !== validLevel) return false;
    if (query) {
      return (
        item.german.toLowerCase().includes(query) ||
        item.english.toLowerCase().includes(query) ||
        item.grammar_info.toLowerCase().includes(query) ||
        item.notes.toLowerCase().includes(query)
      );
    }
    return true;
  });

  results.sort((a, b) => {
    if (a.updated_at !== b.updated_at) {
      return b.updated_at.localeCompare(a.updated_at);
    }
    return b.id - a.id;
  });

  return results.map((item) => ({ ...item }));
}

export function getVocabulary(vocabId: number): VocabularyItem | null {
  const item = vocabularyStore.get(vocabId);
  return item ? { ...item } : null;
}

export function updateVocabulary(
  vocabId: number,
  german: string,
  english: string,
  grammarInfo: string,
  level: string,
  notes = ""
): boolean {
  const existing = vocabularyStore.get(vocabId);
  if (!existing) return false;

  const germanClean = german.trim();
  const englishClean = english.trim();
  if (!germanClean || !englishClean) {
    throw new Error("Both German expression and English meaning are required.");
  }

  const validLevel = validateLevel(level);
  vocabularyStore.set(vocabId, {
    ...existing,
    german: germanClean,
    english: englishClean,
    grammar_info: grammarInfo.trim(),
    level: validLevel,
    notes: notes.trim(),
    updated_at: nowIso(),
  });
  return true;
}

export function deleteVocabulary(vocabId: number): boolean {
  if (!vocabularyStore.has(vocabId)) return false;
  vocabularyStore.delete(vocabId);

  // Cascade delete sentences and their attempts
  for (const [sentenceId, sentence] of sentenceStore.entries()) {
    if (sentence.vocab_id === vocabId) {
      sentenceStore.delete(sentenceId);
      for (const [attemptId, attempt] of attemptStore.entries()) {
        if (attempt.sentence_id === sentenceId) {
          attemptStore.delete(attemptId);
        }
      }
    }
  }
  return true;
}

export function createSentence(
  vocabId: number,
  englishPrompt: string,
  referenceGerman: string,
  level: string,
  contextTag = "",
  structureTag = ""
): number {
  const validLevel = validateLevel(level);
  const id = nextSentenceId++;
  sentenceStore.set(id, {
    id,
    vocab_id: vocabId,
    english_prompt: englishPrompt.trim(),
    reference_german: referenceGerman.trim(),
    context_tag: contextTag.trim(),
    structure_tag: structureTag.trim(),
    level: validLevel,
    is_favorite: false,
    created_at: nowIso(),
  });
  return id;
}

export function getSentence(sentenceId: number): SentenceWithVocab | null {
  const s = sentenceStore.get(sentenceId);
  if (!s) return null;
  const v = vocabularyStore.get(s.vocab_id);
  if (!v) return null;
  return {
    ...s,
    vocab_german: v.german,
    vocab_english: v.english,
    vocab_grammar_info: v.grammar_info,
    vocab_level: v.level,
  };
}

export function getRecentSentencesForVocab(vocabId: number, limit = 8): SentenceItem[] {
  return Array.from(sentenceStore.values())
    .filter((s) => s.vocab_id === vocabId)
    .sort((a, b) => b.id - a.id)
    .slice(0, limit)
    .map((s) => ({ ...s }));
}

export function setSentenceFavorite(sentenceId: number, isFavorite: boolean): boolean {
  const existing = sentenceStore.get(sentenceId);
  if (!existing) return false;
  sentenceStore.set(sentenceId, { ...existing, is_favorite: Boolean(isFavorite) });
  return true;
}

export function listFavoriteSentences(search = "", level = "All"): FavoriteSentenceItem[] {
  let validLevel: CefrLevel | null = null;
  if (level && level !== "All") {
    validLevel = validateLevel(level);
  }
  const query = search.trim().toLowerCase();

  const items: FavoriteSentenceItem[] = [];
  const sortedSentences = Array.from(sentenceStore.values())
    .filter((s) => s.is_favorite)
    .sort((a, b) => b.id - a.id);

  for (const s of sortedSentences) {
    if (validLevel && s.level !== validLevel) continue;
    const v = vocabularyStore.get(s.vocab_id);
    if (!v) continue;

    if (query) {
      const matches =
        s.english_prompt.toLowerCase().includes(query) ||
        s.reference_german.toLowerCase().includes(query) ||
        s.context_tag.toLowerCase().includes(query) ||
        v.german.toLowerCase().includes(query) ||
        v.english.toLowerCase().includes(query);
      if (!matches) continue;
    }

    const latestAttempt = getLatestAttemptForSentence(s.id);
    items.push({
      id: s.id,
      vocab_id: s.vocab_id,
      english_prompt: s.english_prompt,
      reference_german: s.reference_german,
      context_tag: s.context_tag,
      structure_tag: s.structure_tag,
      level: s.level,
      is_favorite: s.is_favorite,
      created_at: s.created_at,
      vocab_german: v.german,
      vocab_english: v.english,
      vocab_grammar_info: v.grammar_info,
      latest_attempt: latestAttempt,
    });
  }

  return items;
}

export function saveAttempt(params: {
  sentenceId: number;
  userTranslation: string;
  verdict: Verdict;
  grammarCorrect: boolean;
  semanticAccurate: boolean;
  grammarSummary: string;
  semanticSummary: string;
  score: number;
  correctedGerman: string;
  grammarFeedback?: string;
  wordOrderFeedback?: string;
  naturalExpressions?: string;
  alternatives?: string[];
}): number {
  if (!VALID_VERDICTS.includes(params.verdict)) {
    throw new Error(`Verdict must be one of ${VALID_VERDICTS.join(", ")}, got '${params.verdict}'`);
  }
  const boundedScore = Math.max(0, Math.min(100, Math.round(Number(params.score) || 0)));
  const id = nextAttemptId++;
  attemptStore.set(id, {
    id,
    sentence_id: params.sentenceId,
    user_translation: params.userTranslation.trim(),
    verdict: params.verdict,
    grammar_correct: Boolean(params.grammarCorrect),
    semantic_accurate: Boolean(params.semanticAccurate),
    grammar_summary: params.grammarSummary.trim(),
    semantic_summary: params.semanticSummary.trim(),
    score: boundedScore,
    corrected_german: params.correctedGerman.trim(),
    grammar_feedback: (params.grammarFeedback ?? "").trim(),
    word_order_feedback: (params.wordOrderFeedback ?? "").trim(),
    natural_expressions: (params.naturalExpressions ?? "").trim(),
    alternatives: Array.isArray(params.alternatives) ? [...params.alternatives] : [],
    created_at: nowIso(),
  });
  return id;
}

export function listAttemptsForSentence(sentenceId: number): AttemptItem[] {
  return Array.from(attemptStore.values())
    .filter((a) => a.sentence_id === sentenceId)
    .sort((a, b) => b.id - a.id)
    .map((a) => ({ ...a, alternatives: [...a.alternatives] }));
}

export function getLatestAttemptForSentence(sentenceId: number): AttemptItem | null {
  const attempts = listAttemptsForSentence(sentenceId);
  return attempts[0] ?? null;
}
