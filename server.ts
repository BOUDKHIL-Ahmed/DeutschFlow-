import "dotenv/config";
import express, { type Request, type Response } from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  AIServiceError,
  getAiService,
  getSettingsSummary,
  synthesizeGermanSpeech,
  updateRuntimeSettings,
} from "./src/aiService.js";
import {
  addVocabulary,
  createSentence,
  deleteVocabulary,
  getRecentSentencesForVocab,
  getSentence,
  getVocabulary,
  initDb,
  listFavoriteSentences,
  listVocabulary,
  saveAttempt,
  setSentenceFavorite,
  updateVocabulary,
  type SentenceWithVocab,
} from "./src/db.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PWA_DIR = path.join(__dirname, "pwa");

initDb();

function publicSentence(sentence: SentenceWithVocab) {
  return {
    id: sentence.id,
    vocab_id: sentence.vocab_id,
    english_prompt: sentence.english_prompt,
    context_tag: sentence.context_tag,
    structure_tag: sentence.structure_tag,
    level: sentence.level,
    is_favorite: Boolean(sentence.is_favorite),
    created_at: sentence.created_at,
    vocab_german: sentence.vocab_german,
    vocab_english: sentence.vocab_english,
    vocab_grammar_info: sentence.vocab_grammar_info,
  };
}

const app = express();
app.use(express.json());

// ---------------------------------------------------------------------------
// API Endpoints
// ---------------------------------------------------------------------------

app.get("/api/health", (_req: Request, res: Response) => {
  res.json({ status: "ok", app: "DeutschFlow PWA" });
});

app.get("/api/vocab", (req: Request, res: Response) => {
  const search = typeof req.query.search === "string" ? req.query.search : "";
  const level = typeof req.query.level === "string" ? req.query.level : "All";
  try {
    const items = listVocabulary(search, level);
    res.json({ items });
  } catch (err) {
    res.status(400).json({ error: err instanceof Error ? err.message : "Invalid query" });
  }
});

app.post("/api/vocab", (req: Request, res: Response) => {
  const body = (req.body ?? {}) as Record<string, unknown>;
  try {
    const vocabId = addVocabulary(
      String(body.german ?? ""),
      String(body.english ?? ""),
      String(body.grammar_info ?? ""),
      String(body.level ?? "B1"),
      String(body.notes ?? "")
    );
    const item = getVocabulary(vocabId);
    res.status(201).json({ item });
  } catch (err) {
    res.status(400).json({ error: err instanceof Error ? err.message : "Invalid input" });
  }
});

app.put("/api/vocab/:vocabId", (req: Request, res: Response) => {
  const vocabId = Number(req.params.vocabId);
  if (!Number.isInteger(vocabId)) {
    res.status(400).json({ error: "Invalid vocabulary ID." });
    return;
  }
  const body = (req.body ?? {}) as Record<string, unknown>;
  try {
    const updated = updateVocabulary(
      vocabId,
      String(body.german ?? ""),
      String(body.english ?? ""),
      String(body.grammar_info ?? ""),
      String(body.level ?? "B1"),
      String(body.notes ?? "")
    );
    if (!updated) {
      res.status(404).json({ error: "Vocabulary item not found." });
      return;
    }
    const item = getVocabulary(vocabId);
    res.json({ item });
  } catch (err) {
    res.status(400).json({ error: err instanceof Error ? err.message : "Invalid input" });
  }
});

app.delete("/api/vocab/:vocabId", (req: Request, res: Response) => {
  const vocabId = Number(req.params.vocabId);
  if (!Number.isInteger(vocabId)) {
    res.status(400).json({ error: "Invalid vocabulary ID." });
    return;
  }
  const deleted = deleteVocabulary(vocabId);
  if (!deleted) {
    res.status(404).json({ error: "Vocabulary item not found." });
    return;
  }
  res.json({ deleted: true });
});

app.post("/api/practice/generate", async (req: Request, res: Response) => {
  const body = (req.body ?? {}) as Record<string, unknown>;
  const vocabId = Number(body.vocab_id);
  if (!Number.isInteger(vocabId) || vocabId <= 0) {
    res.status(400).json({ error: "Valid vocab_id is required." });
    return;
  }

  const vocab = getVocabulary(vocabId);
  if (!vocab) {
    res.status(404).json({ error: "Vocabulary item not found." });
    return;
  }

  const recent = getRecentSentencesForVocab(vocabId, 8);
  try {
    const service = getAiService();
    const challenge = await service.generateChallenge({
      germanExpression: vocab.german,
      englishMeaning: vocab.english,
      grammarInfo: vocab.grammar_info,
      level: vocab.level,
      recentSentences: recent,
    });

    const sentenceId = createSentence(
      vocab.id,
      challenge.english_prompt,
      challenge.reference_german,
      vocab.level,
      challenge.context_tag,
      challenge.structure_tag
    );
    const sentence = getSentence(sentenceId);
    if (!sentence) {
      res.status(500).json({ error: "Failed to create sentence." });
      return;
    }
    res.status(201).json({ sentence: publicSentence(sentence) });
  } catch (err) {
    if (err instanceof AIServiceError) {
      res.status(502).json({ error: err.message });
      return;
    }
    res.status(500).json({ error: err instanceof Error ? err.message : "Failed to generate challenge." });
  }
});

app.get("/api/sentences/:sentenceId", (req: Request, res: Response) => {
  const sentenceId = Number(req.params.sentenceId);
  if (!Number.isInteger(sentenceId)) {
    res.status(400).json({ error: "Invalid sentence ID." });
    return;
  }
  const sentence = getSentence(sentenceId);
  if (!sentence) {
    res.status(404).json({ error: "Sentence not found." });
    return;
  }
  res.json({ sentence: publicSentence(sentence) });
});

app.post("/api/practice/submit", async (req: Request, res: Response) => {
  const body = (req.body ?? {}) as Record<string, unknown>;
  const sentenceId = Number(body.sentence_id);
  if (!Number.isInteger(sentenceId) || sentenceId <= 0) {
    res.status(400).json({ error: "Valid sentence_id is required." });
    return;
  }

  const userTranslation = String(body.user_translation ?? "").trim();
  if (!userTranslation) {
    res.status(400).json({ error: "Please enter a German translation." });
    return;
  }

  const sentence = getSentence(sentenceId);
  if (!sentence) {
    res.status(404).json({ error: "Sentence not found." });
    return;
  }

  try {
    const service = getAiService();
    const result = await service.evaluateTranslation({
      englishPrompt: sentence.english_prompt,
      userTranslation,
      targetGerman: sentence.vocab_german,
      targetEnglish: sentence.vocab_english,
      targetGrammarInfo: sentence.vocab_grammar_info,
      referenceGerman: sentence.reference_german,
      level: sentence.level,
    });

    const attemptId = saveAttempt({
      sentenceId,
      userTranslation,
      verdict: result.verdict,
      grammarCorrect: result.grammar_correct,
      semanticAccurate: result.semantic_accurate,
      grammarSummary: result.grammar_summary,
      semanticSummary: result.semantic_summary,
      score: result.score,
      correctedGerman: result.corrected_german,
      grammarFeedback: result.grammar_feedback,
      wordOrderFeedback: result.word_order_feedback,
      naturalExpressions: result.natural_expressions,
      alternatives: result.alternatives,
    });

    res.json({
      attempt_id: attemptId,
      is_favorite: Boolean(sentence.is_favorite),
      reference_german: sentence.reference_german,
      provider_used: service.lastProviderUsed,
      evaluation: result,
    });
  } catch (err) {
    if (err instanceof AIServiceError) {
      res.status(502).json({ error: err.message });
      return;
    }
    res.status(500).json({ error: err instanceof Error ? err.message : "Failed to evaluate translation." });
  }
});

app.post("/api/sentences/:sentenceId/favorite", (req: Request, res: Response) => {
  const sentenceId = Number(req.params.sentenceId);
  if (!Number.isInteger(sentenceId)) {
    res.status(400).json({ error: "Invalid sentence ID." });
    return;
  }
  const body = (req.body ?? {}) as Record<string, unknown>;
  const isFavorite = body.is_favorite !== undefined ? Boolean(body.is_favorite) : true;
  const updated = setSentenceFavorite(sentenceId, isFavorite);
  if (!updated) {
    res.status(404).json({ error: "Sentence not found." });
    return;
  }
  res.json({ sentence_id: sentenceId, is_favorite: isFavorite });
});

app.get("/api/favorites", (req: Request, res: Response) => {
  const search = typeof req.query.search === "string" ? req.query.search : "";
  const level = typeof req.query.level === "string" ? req.query.level : "All";
  try {
    const items = listFavoriteSentences(search, level);
    res.json({ items });
  } catch (err) {
    res.status(400).json({ error: err instanceof Error ? err.message : "Invalid query" });
  }
});

app.get("/api/settings", (_req: Request, res: Response) => {
  res.json(getSettingsSummary());
});

app.post("/api/settings", (req: Request, res: Response) => {
  const body = (req.body ?? {}) as Record<string, unknown>;
  const summary = updateRuntimeSettings({
    provider: typeof body.provider === "string" ? body.provider : undefined,
    groq_model: typeof body.groq_model === "string" ? body.groq_model : undefined,
    gemini_model: typeof body.gemini_model === "string" ? body.gemini_model : undefined,
  });
  res.json(summary);
});

app.post("/api/tts", async (req: Request, res: Response) => {
  const body = (req.body ?? {}) as Record<string, unknown>;
  const text = String(body.text ?? "").trim();
  if (!text) {
    res.status(400).json({ error: "Text is required for speech synthesis." });
    return;
  }

  const voice = typeof body.voice === "string" ? body.voice : undefined;
  try {
    const result = await synthesizeGermanSpeech(text, voice);
    res.json({
      audio_base64: result.audioBase64,
      mime_type: result.mimeType,
      voice: result.voice,
    });
  } catch (err) {
    if (err instanceof AIServiceError) {
      res.status(502).json({ error: err.message });
      return;
    }
    res.status(500).json({ error: err instanceof Error ? err.message : "Failed to synthesize speech." });
  }
});

// ---------------------------------------------------------------------------
// PWA Static Endpoints
// ---------------------------------------------------------------------------

app.get("/", (_req: Request, res: Response) => {
  res.setHeader("Cache-Control", "no-cache");
  res.sendFile(path.join(PWA_DIR, "index.html"));
});

app.get("/manifest.json", (_req: Request, res: Response) => {
  res.setHeader("Cache-Control", "no-cache");
  res.type("application/manifest+json");
  res.sendFile(path.join(PWA_DIR, "manifest.json"));
});

app.get("/sw.js", (_req: Request, res: Response) => {
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Service-Worker-Allowed", "/");
  res.type("application/javascript");
  res.sendFile(path.join(PWA_DIR, "sw.js"));
});

app.use("/static", express.static(PWA_DIR));

const port = Number(process.env.PORT) || 3000;
app.listen(port, "0.0.0.0", () => {
  console.log(`DeutschFlow running on http://0.0.0.0:${port}`);
});
