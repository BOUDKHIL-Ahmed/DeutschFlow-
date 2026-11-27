import { GoogleGenAI, Type, type Schema } from "@google/genai";
import type { SentenceItem, Verdict } from "./db.js";

export const VALID_PROVIDERS = ["groq_first", "gemini_first", "groq", "gemini"] as const;
export type AIProviderMode = (typeof VALID_PROVIDERS)[number];

export const DEFAULT_GEMINI_MODEL = process.env.GEMINI_MODEL?.trim() || "gemini-4-hydrogen";
export const DEFAULT_GROQ_MODEL = process.env.GROQ_MODEL?.trim() || "openai/gpt-oss-120b";
export const DEFAULT_TTS_MODEL = "gemini-3.8-flash-lite-tts";
export const VALID_TTS_VOICES = ["Kore", "Zephyr", "Puck", "Charon", "Fenrir"] as const;
export type TtsVoiceName = (typeof VALID_TTS_VOICES)[number];
const GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions";

export class AIServiceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AIServiceError";
  }
}

export interface GeneratedChallenge {
  english_prompt: string;
  reference_german: string;
  context_tag: string;
  structure_tag: string;
}

export interface TranslationEvaluation {
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
}

// Runtime settings (initialized from environment variables; keys stay server-side only)
let runtimeProvider: AIProviderMode = (() => {
  const envProvider = (process.env.AI_PROVIDER || "").trim().toLowerCase();
  if (VALID_PROVIDERS.includes(envProvider as AIProviderMode)) {
    return envProvider as AIProviderMode;
  }
  const hasGroq = Boolean(cleanKey(process.env.GROQ_API_KEY, "your_groq_api_key_here"));
  return hasGroq ? "groq_first" : "gemini_first";
})();

let runtimeGeminiModel = DEFAULT_GEMINI_MODEL;
let runtimeGroqModel = DEFAULT_GROQ_MODEL;

function cleanKey(raw: string | undefined, placeholder: string): string {
  const val = (raw || "").trim();
  if (!val || val === placeholder) return "";
  return val;
}

export function getSettingsSummary() {
  const groqKey = cleanKey(process.env.GROQ_API_KEY, "your_groq_api_key_here");
  const geminiKey = cleanKey(
    process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY,
    "your_gemini_api_key_here"
  );
  return {
    has_groq: Boolean(groqKey),
    has_gemini: Boolean(geminiKey),
    provider: runtimeProvider,
    groq_model: runtimeGroqModel,
    gemini_model: runtimeGeminiModel,
  };
}

export function updateRuntimeSettings(input: {
  provider?: string;
  groq_model?: string;
  gemini_model?: string;
}) {
  if (input.provider) {
    const normalized = input.provider.trim().toLowerCase();
    if (VALID_PROVIDERS.includes(normalized as AIProviderMode)) {
      runtimeProvider = normalized as AIProviderMode;
    }
  }
  if (input.groq_model && input.groq_model.trim()) {
    runtimeGroqModel = input.groq_model.trim();
  }
  if (input.gemini_model && input.gemini_model.trim()) {
    runtimeGeminiModel = input.gemini_model.trim();
  }
  return getSettingsSummary();
}

const CHALLENGE_RESPONSE_SCHEMA: Schema = {
  type: Type.OBJECT,
  properties: {
    english_prompt: {
      type: Type.STRING,
      description: "Natural, idiomatic English sentence for the learner to translate into German.",
    },
    reference_german: {
      type: Type.STRING,
      description: "One natural German translation using the target German expression.",
    },
    context_tag: {
      type: Type.STRING,
      description: "Short 1-3 word situation label (e.g. 'workplace', 'travel', 'friendship').",
    },
    structure_tag: {
      type: Type.STRING,
      description: "Short 1-4 word grammar structure label (e.g. 'subordinate clause', 'Konjunktiv II').",
    },
  },
  required: ["english_prompt", "reference_german", "context_tag", "structure_tag"],
};

const EVALUATION_RESPONSE_SCHEMA: Schema = {
  type: Type.OBJECT,
  properties: {
    verdict: {
      type: Type.STRING,
      description: "Must be one of: 'correct', 'minor_issues', 'needs_work'.",
    },
    grammar_correct: {
      type: Type.BOOLEAN,
      description:
        "True only if the German sentence has no actual grammatical, inflectional, case, preposition, or word-order errors.",
    },
    semantic_accurate: {
      type: Type.BOOLEAN,
      description: "True if the German sentence accurately conveys the meaning of the English prompt.",
    },
    grammar_summary: {
      type: Type.STRING,
      description: "One concise sentence summarizing grammatical correctness.",
    },
    semantic_summary: {
      type: Type.STRING,
      description: "One concise sentence summarizing semantic accuracy and target-expression usage.",
    },
    score: {
      type: Type.INTEGER,
      description: "Holistic quality score from 0 to 100 matching verdict.",
    },
    corrected_german: {
      type: Type.STRING,
      description: "Minimally corrected version of the learner's German sentence preserving their valid structure.",
    },
    grammar_feedback: {
      type: Type.STRING,
      description:
        "Detailed explanation of actual mistakes in cases, articles, prepositions, conjugation, and agreement. State clearly if there are no grammatical errors.",
    },
    word_order_feedback: {
      type: Type.STRING,
      description:
        "Explanation of any word order errors (V2, verb-final, Satzklammer, TeKaMoLo, pronoun order) or confirmation that word order is valid.",
    },
    natural_expressions: {
      type: Type.STRING,
      description: "Optional stylistic or idiomatic suggestions, clearly distinguished from actual mistakes.",
    },
    alternatives: {
      type: Type.ARRAY,
      items: { type: Type.STRING },
      description: "2 to 3 valid, natural alternative German translations.",
    },
  },
  required: [
    "verdict",
    "grammar_correct",
    "semantic_accurate",
    "grammar_summary",
    "semantic_summary",
    "score",
    "corrected_german",
    "grammar_feedback",
    "word_order_feedback",
    "natural_expressions",
    "alternatives",
  ],
};

const CHALLENGE_JSON_SCHEMA_TEXT = JSON.stringify({
  type: "object",
  properties: {
    english_prompt: { type: "string" },
    reference_german: { type: "string" },
    context_tag: { type: "string" },
    structure_tag: { type: "string" },
  },
  required: ["english_prompt", "reference_german", "context_tag", "structure_tag"],
});

const EVALUATION_JSON_SCHEMA_TEXT = JSON.stringify({
  type: "object",
  properties: {
    verdict: { type: "string", enum: ["correct", "minor_issues", "needs_work"] },
    grammar_correct: { type: "boolean" },
    semantic_accurate: { type: "boolean" },
    grammar_summary: { type: "string" },
    semantic_summary: { type: "string" },
    score: { type: "integer", minimum: 0, maximum: 100 },
    corrected_german: { type: "string" },
    grammar_feedback: { type: "string" },
    word_order_feedback: { type: "string" },
    natural_expressions: { type: "string" },
    alternatives: { type: "array", items: { type: "string" } },
  },
  required: [
    "verdict",
    "grammar_correct",
    "semantic_accurate",
    "grammar_summary",
    "semantic_summary",
    "score",
    "corrected_german",
    "grammar_feedback",
    "word_order_feedback",
    "natural_expressions",
    "alternatives",
  ],
});

const GENERATOR_SYSTEM_PROMPT = `You are an expert German-as-a-foreign-language tutor creating translation challenges for an English-speaking learner.

Your job is to produce ONE natural English sentence that the learner will translate into German, along with one reference German translation.

Rules:
1. The English sentence must sound completely natural and idiomatic—never robotic or textbook-stiff.
2. Place the sentence in a realistic everyday, workplace, travel, social, or cultural situation.
3. Match the requested CEFR level (A2, B1, or B2) in vocabulary and clause complexity.
4. Make sure translating the English sentence naturally invites using the target German word or expression.
5. Vary sentence structures (questions, subordinate clauses with weil/obwohl/dass/wenn, relative clauses, Perfekt/Präteritum, modal verbs, Konjunktiv II, passive, etc.) and avoid repeating recent sentences, contexts, or structures provided to you.
6. Do NOT include the German word or hints inside \`english_prompt\`.`;

const EVALUATOR_SYSTEM_PROMPT = `You are a strict but fair native-level German teacher evaluating an English-to-German translation.

Core evaluation principles:
1. Evaluate GRAMMATICAL CORRECTNESS and SEMANTIC ACCURACY separately.
   - \`grammar_correct\`: Is the German grammatically valid (cases, articles, adjective endings, prepositions, verb conjugation, tense auxiliaries, noun capitalization, word order)?
   - \`semantic_accurate\`: Does the German accurately convey the full meaning of the English prompt?
2. NEVER compare the learner's answer word-for-word against the reference German translation. The reference translation is only ONE possible rendering.
3. Accept any valid, natural German construction—even if the learner chose different phrasing, synonyms, clause ordering, or register (du/Sie, Perfekt/Präteritum where interchangeable) that fits the English prompt.
4. Clearly distinguish ACTUAL MISTAKES from OPTIONAL STYLISTIC IMPROVEMENTS:
   - Do not mark a valid sentence wrong just because another phrasing sounds slightly more idiomatic.
   - If there are no actual grammatical mistakes, set \`grammar_correct = true\` and explicitly say there are no grammatical errors before sharing any optional style tips in \`natural_expressions\`.
5. Explain actual errors concretely and clearly:
   - Cases (Nominativ, Akkusativ, Dativ, Genitiv)
   - Articles & determiners (gender, number, case endings)
   - Prepositions (choice and governed case)
   - Verb conjugation & valence (person, number, tense, separable prefix, reflexive pronoun)
   - Word order (V2 main clause, verb-final subordinate clause, Satzklammer, TeKaMoLo, negation placement)
6. For \`corrected_german\`, fix ONLY what is actually wrong in the learner's own sentence while preserving their chosen structure whenever possible. If their sentence is already valid, return their sentence (fixing at most punctuation/capitalization if needed).
7. Note whether the target German expression was used naturally; if they conveyed the meaning accurately with another valid expression, still acknowledge semantic accuracy and mention the target expression in \`natural_expressions\` or \`semantic_summary\`.
8. Verdict rules:
   - "correct": \`grammar_correct\` is true AND \`semantic_accurate\` is true (score 90-100).
   - "minor_issues": mostly accurate with 1-2 small grammar, spelling, or nuance slips (score 60-89).
   - "needs_work": major grammatical errors, broken word order, or clear meaning mismatch (score 0-59).`;

function buildChallengePrompt(params: {
  germanExpression: string;
  englishMeaning: string;
  grammarInfo: string;
  level: string;
  recentSentences?: SentenceItem[];
}): string {
  const recentLines = (params.recentSentences ?? [])
    .slice(0, 8)
    .map(
      (item) =>
        `- [${item.context_tag || ""} | ${item.structure_tag || ""}] ${item.english_prompt || ""}`
    );
  const recentBlock = recentLines.length ? recentLines.join("\n") : "None yet.";

  return (
    `Target German expression: ${params.germanExpression}\n` +
    `English meaning: ${params.englishMeaning}\n` +
    `Grammar info: ${params.grammarInfo || "Not specified"}\n` +
    `Target CEFR level: ${params.level}\n\n` +
    `Recent prompts to avoid repeating (use a fresh situation and sentence structure):\n` +
    `${recentBlock}\n`
  );
}

function buildEvaluationPrompt(params: {
  englishPrompt: string;
  userTranslation: string;
  targetGerman: string;
  targetEnglish: string;
  targetGrammarInfo: string;
  referenceGerman: string;
  level: string;
}): string {
  return (
    `CEFR level: ${params.level}\n` +
    `Target vocabulary expression: ${params.targetGerman} (${params.targetEnglish})\n` +
    `Target grammar notes: ${params.targetGrammarInfo || "None"}\n\n` +
    `English prompt shown to learner:\n${params.englishPrompt}\n\n` +
    `One possible reference translation (do NOT compare word-for-word):\n${params.referenceGerman}\n\n` +
    `Learner's German translation:\n${params.userTranslation}\n`
  );
}

function cleanJsonText(raw: string): string {
  let text = raw.trim();
  if (text.startsWith("```")) {
    text = text.replace(/^```(?:json)?\s*/i, "");
    text = text.replace(/\s*```$/, "");
  }
  return text.trim();
}

function isTransientError(err: unknown): boolean {
  const msg = String(err instanceof Error ? err.message : err).toUpperCase();
  return ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "TIMEOUT"].some((code) =>
    msg.includes(code)
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeVerdict(raw: unknown): Verdict {
  if (raw === "correct" || raw === "minor_issues" || raw === "needs_work") {
    return raw;
  }
  return "needs_work";
}

interface Backend {
  name: string;
  model: string;
  runStructured<T>(params: {
    systemPrompt: string;
    userPrompt: string;
    geminiSchema: Schema;
    jsonSchemaText: string;
    temperature: number;
  }): Promise<T>;
}

class GeminiBackend implements Backend {
  name = "Gemini";
  model: string;
  private ai: GoogleGenAI;

  constructor(apiKey: string, model: string) {
    this.model = model;
    this.ai = new GoogleGenAI({
      apiKey,
      httpOptions: {
        headers: {
          "User-Agent": "aistudio-build",
        },
      },
    });
  }

  async runStructured<T>(params: {
    systemPrompt: string;
    userPrompt: string;
    geminiSchema: Schema;
    jsonSchemaText: string;
    temperature: number;
  }): Promise<T> {
    let lastErr: unknown;
    const isGemini4 = this.model.startsWith("gemini-4-");

    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const response = await this.ai.models.generateContent({
          model: this.model,
          contents: params.userPrompt,
          config: {
            systemInstruction: params.systemPrompt,
            responseMimeType: "application/json",
            responseSchema: params.geminiSchema,
            ...(isGemini4 ? {} : { temperature: params.temperature }),
          },
        });
        const rawText = (response.text ?? "").trim();
        if (!rawText) {
          throw new AIServiceError("Gemini returned an empty response.");
        }
        return JSON.parse(cleanJsonText(rawText)) as T;
      } catch (err) {
        lastErr = err;
        if (attempt < 2 && isTransientError(err)) {
          await sleep(800 * (attempt + 1));
          continue;
        }
        break;
      }
    }
    const msg = lastErr instanceof Error ? lastErr.message : String(lastErr);
    throw new AIServiceError(`Gemini (${this.model}): ${msg}`);
  }
}

class GroqBackend implements Backend {
  name = "Groq";
  model: string;
  private apiKey: string;

  constructor(apiKey: string, model: string) {
    this.apiKey = apiKey;
    this.model = model;
  }

  async runStructured<T>(params: {
    systemPrompt: string;
    userPrompt: string;
    geminiSchema: Schema;
    jsonSchemaText: string;
    temperature: number;
  }): Promise<T> {
    const jsonSystem =
      `${params.systemPrompt}\n\n` +
      `Return ONLY a single valid JSON object matching this JSON Schema (no markdown, no extra text):\n` +
      `${params.jsonSchemaText}`;

    const body = JSON.stringify({
      model: this.model,
      messages: [
        { role: "system", content: jsonSystem },
        { role: "user", content: params.userPrompt },
      ],
      temperature: params.temperature,
      response_format: { type: "json_object" },
    });

    let lastErr: unknown;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const resp = await fetch(GROQ_CHAT_URL, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${this.apiKey}`,
            "Content-Type": "application/json",
          },
          body,
          signal: AbortSignal.timeout(30000),
        });
        if (!resp.ok) {
          const errText = await resp.text();
          throw new AIServiceError(`HTTP ${resp.status}: ${errText.slice(0, 300)}`);
        }
        const data = (await resp.json()) as {
          choices?: Array<{ message?: { content?: string } }>;
        };
        const content = data.choices?.[0]?.message?.content ?? "";
        if (!content) {
          throw new AIServiceError("Groq returned an empty response.");
        }
        return JSON.parse(cleanJsonText(content)) as T;
      } catch (err) {
        lastErr = err;
        if (attempt < 2 && isTransientError(err)) {
          await sleep(700 * (attempt + 1));
          continue;
        }
        break;
      }
    }
    const msg = lastErr instanceof Error ? lastErr.message : String(lastErr);
    throw new AIServiceError(`Groq (${this.model}): ${msg}`);
  }
}

export class AIService {
  lastProviderUsed = "";
  private backends: Backend[] = [];

  constructor() {
    const geminiKey = cleanKey(
      process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY,
      "your_gemini_api_key_here"
    );
    const groqKey = cleanKey(process.env.GROQ_API_KEY, "your_groq_api_key_here");

    const geminiBackend = geminiKey ? new GeminiBackend(geminiKey, runtimeGeminiModel) : null;
    const groqBackend = groqKey ? new GroqBackend(groqKey, runtimeGroqModel) : null;

    if (runtimeProvider === "groq") {
      if (groqBackend) this.backends.push(groqBackend);
    } else if (runtimeProvider === "gemini") {
      if (geminiBackend) this.backends.push(geminiBackend);
    } else if (runtimeProvider === "gemini_first") {
      if (geminiBackend) this.backends.push(geminiBackend);
      if (groqBackend) this.backends.push(groqBackend);
    } else {
      if (groqBackend) this.backends.push(groqBackend);
      if (geminiBackend) this.backends.push(geminiBackend);
    }

    if (this.backends.length === 0) {
      throw new AIServiceError(
        "Missing API key. Configure GEMINI_API_KEY or GROQ_API_KEY in environment secrets."
      );
    }
  }

  private async execute<T>(params: {
    systemPrompt: string;
    userPrompt: string;
    geminiSchema: Schema;
    jsonSchemaText: string;
    temperature: number;
  }): Promise<T> {
    const errors: string[] = [];
    for (const backend of this.backends) {
      try {
        const result = await backend.runStructured<T>(params);
        this.lastProviderUsed = `${backend.name} (${backend.model})`;
        return result;
      } catch (err) {
        errors.push(err instanceof Error ? err.message : String(err));
      }
    }
    throw new AIServiceError("All configured AI providers failed: " + errors.join(" | "));
  }

  async generateChallenge(params: {
    germanExpression: string;
    englishMeaning: string;
    grammarInfo: string;
    level: string;
    recentSentences?: SentenceItem[];
  }): Promise<GeneratedChallenge> {
    const userPrompt = buildChallengePrompt(params);
    const parsed = await this.execute<GeneratedChallenge>({
      systemPrompt: GENERATOR_SYSTEM_PROMPT,
      userPrompt,
      geminiSchema: CHALLENGE_RESPONSE_SCHEMA,
      jsonSchemaText: CHALLENGE_JSON_SCHEMA_TEXT,
      temperature: 0.9,
    });

    return {
      english_prompt: String(parsed.english_prompt ?? "").trim(),
      reference_german: String(parsed.reference_german ?? "").trim(),
      context_tag: String(parsed.context_tag ?? "").trim(),
      structure_tag: String(parsed.structure_tag ?? "").trim(),
    };
  }

  async evaluateTranslation(params: {
    englishPrompt: string;
    userTranslation: string;
    targetGerman: string;
    targetEnglish: string;
    targetGrammarInfo: string;
    referenceGerman: string;
    level: string;
  }): Promise<TranslationEvaluation> {
    const userPrompt = buildEvaluationPrompt(params);
    const parsed = await this.execute<TranslationEvaluation>({
      systemPrompt: EVALUATOR_SYSTEM_PROMPT,
      userPrompt,
      geminiSchema: EVALUATION_RESPONSE_SCHEMA,
      jsonSchemaText: EVALUATION_JSON_SCHEMA_TEXT,
      temperature: 0.2,
    });

    return {
      verdict: normalizeVerdict(parsed.verdict),
      grammar_correct: Boolean(parsed.grammar_correct),
      semantic_accurate: Boolean(parsed.semantic_accurate),
      grammar_summary: String(parsed.grammar_summary ?? "").trim(),
      semantic_summary: String(parsed.semantic_summary ?? "").trim(),
      score: Math.max(0, Math.min(100, Math.round(Number(parsed.score) || 0))),
      corrected_german: String(parsed.corrected_german ?? "").trim(),
      grammar_feedback: String(parsed.grammar_feedback ?? "").trim(),
      word_order_feedback: String(parsed.word_order_feedback ?? "").trim(),
      natural_expressions: String(parsed.natural_expressions ?? "").trim(),
      alternatives: Array.isArray(parsed.alternatives)
        ? parsed.alternatives.map((a) => String(a).trim()).filter(Boolean)
        : [],
    };
  }
}

export function getAiService(): AIService {
  return new AIService();
}

const MAX_TTS_CACHE_ENTRIES = 60;
const ttsCache = new Map<string, { audioBase64: string; mimeType: string }>();

export async function synthesizeGermanSpeech(
  text: string,
  voiceName?: string
): Promise<{ audioBase64: string; mimeType: string; voice: TtsVoiceName }> {
  const cleanedText = text.trim();
  if (!cleanedText) {
    throw new AIServiceError("German text is required for speech synthesis.");
  }
  if (cleanedText.length > 600) {
    throw new AIServiceError("Text is too long for single-sentence voice playback.");
  }

  const geminiKey = cleanKey(
    process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY,
    "your_gemini_api_key_here"
  );
  if (!geminiKey) {
    throw new AIServiceError(
      "Missing GEMINI_API_KEY for natural German voice synthesis."
    );
  }

  const normalizedVoice = (voiceName || "").trim();
  const validVoice: TtsVoiceName = VALID_TTS_VOICES.includes(normalizedVoice as TtsVoiceName)
    ? (normalizedVoice as TtsVoiceName)
    : "Kore";

  const cacheKey = `${validVoice}:${cleanedText}`;
  const cached = ttsCache.get(cacheKey);
  if (cached) {
    return { ...cached, voice: validVoice };
  }

  const ai = new GoogleGenAI({
    apiKey: geminiKey,
    httpOptions: {
      headers: {
        "User-Agent": "aistudio-build",
      },
    },
  });

  let lastErr: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await ai.models.generateContent({
        model: DEFAULT_TTS_MODEL,
        contents: [
          {
            role: "user",
            parts: [
              {
                text: cleanedText,
                speechMetadata: {
                  style:
                    "Speak naturally and clearly in standard German at a comfortable learner-friendly pace.",
                },
              },
            ],
          },
        ],
        config: {
          responseModalities: ["AUDIO"],
          speechConfig: {
            voiceConfig: {
              prebuiltVoiceConfig: { voiceName: validVoice },
            },
          },
        },
      });

      const parts = response.candidates?.[0]?.content?.parts ?? [];
      const audioPart = parts.find((p) => p.inlineData?.data);
      const audioBase64 = audioPart?.inlineData?.data;
      const mimeType = audioPart?.inlineData?.mimeType || "audio/wav";

      if (!audioBase64) {
        throw new AIServiceError("TTS model returned no audio data.");
      }

      if (ttsCache.size >= MAX_TTS_CACHE_ENTRIES) {
        const oldestKey = ttsCache.keys().next().value;
        if (oldestKey !== undefined) {
          ttsCache.delete(oldestKey);
        }
      }
      ttsCache.set(cacheKey, { audioBase64, mimeType });

      return { audioBase64, mimeType, voice: validVoice };
    } catch (err) {
      lastErr = err;
      if (attempt < 2 && isTransientError(err)) {
        await sleep(700 * (attempt + 1));
        continue;
      }
      break;
    }
  }

  const msg = lastErr instanceof Error ? lastErr.message : String(lastErr);
  throw new AIServiceError(`Gemini TTS (${DEFAULT_TTS_MODEL}): ${msg}`);
}

