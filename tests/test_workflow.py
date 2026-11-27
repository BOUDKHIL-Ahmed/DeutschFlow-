"""End-to-end tests for DeutschFlow database, AI service isolation, and Streamlit UI."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ai_service
import db
import pwa_server
from starlette.testclient import TestClient
from streamlit.testing.v1 import AppTest


class _FakeModels:
    """Stub for google.genai Client.models supporting deterministic schema responses."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: str, config: object):
        self.calls.append({"model": model, "contents": contents, "config": config})
        schema = getattr(config, "response_schema", None)

        if schema is ai_service._ChallengeSchema:
            return SimpleNamespace(
                parsed=ai_service._ChallengeSchema(
                    english_prompt="Even when things get hectic at work, I can always rely on my colleagues.",
                    reference_german="Selbst wenn es bei der Arbeit hektisch wird, kann ich mich immer auf meine Kollegen verlassen.",
                    context_tag="workplace",
                    structure_tag="subordinate clause + modal",
                ),
                text="",
            )

        if schema is ai_service._EvaluationSchema:
            return SimpleNamespace(
                parsed=ai_service._EvaluationSchema(
                    verdict="minor_issues",
                    grammar_correct=False,
                    semantic_accurate=True,
                    grammar_summary="One preposition/case error; sentence structure is otherwise sound.",
                    semantic_summary="Accurately conveys the full English meaning using the target expression.",
                    score=82,
                    corrected_german=(
                        "Auch wenn es im Büro stressig ist, kann ich mich immer auf meine Kollegen verlassen."
                    ),
                    grammar_feedback=(
                        "Preposition/case: 'verlassen auf' takes Akkusativ ('auf meine Kollegen'), "
                        "not Dativ ('auf meinen Kollegen'). Verb conjugation ('kann') and subordinate "
                        "clause verb-final position ('ist') are correct."
                    ),
                    word_order_feedback="Word order is correct (verb-final in 'wenn'-clause, V2 inversion in main clause).",
                    natural_expressions=(
                        "Optional stylistic tip: 'Selbst wenn es bei der Arbeit hektisch wird' sounds slightly more idiomatic, "
                        "though your phrasing 'Auch wenn es im Büro stressig ist' is completely natural."
                    ),
                    alternatives=[
                        "Selbst wenn es bei der Arbeit hektisch wird, kann ich mich stets auf meine Kollegen verlassen.",
                        "Ich kann mich immer auf meine Kollegen verlassen, auch wenn es im Büro stressig ist.",
                    ],
                ),
                text="",
            )

        raise AssertionError(f"Unexpected response_schema: {schema}")


class _FakeGenAIClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.models = _FakeModels()


class DeutschFlowWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_deutschflow.db"
        db.init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_complete_backend_workflow(self) -> None:
        # 1. Add vocabulary
        vocab_id = db.add_vocabulary(
            german="sich auf jdn. verlassen",
            english="to rely on someone",
            grammar_info="reflexive verb + auf (Akk.)",
            level="B1",
            notes="Seen in news article",
            db_path=self.db_path,
        )
        vocab = db.get_vocabulary(vocab_id, db_path=self.db_path)
        self.assertIsNotNone(vocab)
        self.assertEqual(vocab["level"], "B1")

        # Search & edit vocabulary
        found = db.list_vocabulary(search="verlassen", level="B1", db_path=self.db_path)
        self.assertEqual(len(found), 1)
        db.update_vocabulary(
            vocab_id,
            german="sich auf jdn./etw. verlassen",
            english="to rely on someone/something",
            grammar_info="reflexive verb + auf (Akk.)",
            level="B1",
            notes="Updated note",
            db_path=self.db_path,
        )
        vocab = db.get_vocabulary(vocab_id, db_path=self.db_path)
        self.assertEqual(vocab["notes"], "Updated note")

        # 2. Generate English challenge via isolated AI service
        with patch.object(ai_service.genai, "Client", _FakeGenAIClient):
            service = ai_service.get_ai_service(api_key="test-key", model="gemini-2.5-flash")
            challenge = service.generate_challenge(
                german_expression=vocab["german"],
                english_meaning=vocab["english"],
                grammar_info=vocab["grammar_info"],
                level=vocab["level"],
                recent_sentences=[],
            )

        self.assertIn("rely on", challenge.english_prompt)
        sentence_id = db.create_sentence(
            vocab_id=vocab_id,
            english_prompt=challenge.english_prompt,
            reference_german=challenge.reference_german,
            level=vocab["level"],
            context_tag=challenge.context_tag,
            structure_tag=challenge.structure_tag,
            db_path=self.db_path,
        )

        # 3. Submit German translation & receive AI feedback
        user_answer = "Auch wenn es im Büro stressig ist, kann ich mich immer auf meinen Kollegen verlassen."
        with patch.object(ai_service.genai, "Client", _FakeGenAIClient):
            service = ai_service.get_ai_service(api_key="test-key", model="gemini-2.5-flash")
            evaluation = service.evaluate_translation(
                english_prompt=challenge.english_prompt,
                user_translation=user_answer,
                target_german=vocab["german"],
                target_english=vocab["english"],
                target_grammar_info=vocab["grammar_info"],
                reference_german=challenge.reference_german,
                level=vocab["level"],
            )

        self.assertFalse(evaluation.grammar_correct)
        self.assertTrue(evaluation.semantic_accurate)
        self.assertEqual(evaluation.verdict, "minor_issues")
        self.assertEqual(len(evaluation.alternatives), 2)

        # 4. Save the attempt
        attempt_id = db.save_attempt(
            sentence_id=sentence_id,
            user_translation=user_answer,
            verdict=evaluation.verdict,
            grammar_correct=evaluation.grammar_correct,
            semantic_accurate=evaluation.semantic_accurate,
            grammar_summary=evaluation.grammar_summary,
            semantic_summary=evaluation.semantic_summary,
            score=evaluation.score,
            corrected_german=evaluation.corrected_german,
            grammar_feedback=evaluation.grammar_feedback,
            word_order_feedback=evaluation.word_order_feedback,
            natural_expressions=evaluation.natural_expressions,
            alternatives=evaluation.alternatives,
            db_path=self.db_path,
        )
        self.assertGreater(attempt_id, 0)

        saved_attempts = db.list_attempts_for_sentence(sentence_id, db_path=self.db_path)
        self.assertEqual(len(saved_attempts), 1)
        self.assertFalse(saved_attempts[0]["grammar_correct"])
        self.assertTrue(saved_attempts[0]["semantic_accurate"])

        # 5. Favorite the sentence
        toggled = db.set_sentence_favorite(sentence_id, True, db_path=self.db_path)
        self.assertTrue(toggled)

        # 6. Retrieve it from Favorites
        favorites = db.list_favorite_sentences(search="workplace", level="B1", db_path=self.db_path)
        self.assertEqual(len(favorites), 1)
        self.assertEqual(favorites[0]["id"], sentence_id)
        self.assertIsNotNone(favorites[0]["latest_attempt"])
        self.assertEqual(favorites[0]["latest_attempt"]["id"], attempt_id)

    def test_streamlit_ui_end_to_end(self) -> None:
        app_path = Path(__file__).resolve().parent.parent / "app.py"

        with (
            patch.object(db, "DEFAULT_DB_PATH", self.db_path),
            patch.object(ai_service.genai, "Client", _FakeGenAIClient),
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "GROQ_API_KEY": "",
                    "AI_PROVIDER": "gemini",
                },
            ),
        ):
            at = AppTest.from_file(str(app_path), default_timeout=15)
            at.run()
            self.assertFalse(at.exception)

            # Empty state redirects to Vocabulary
            go_vocab_btn = [b for b in at.button if b.label == "Go to Vocabulary"][0]
            go_vocab_btn.click().run()
            self.assertFalse(at.exception)

            # 1. Add vocabulary via Vocabulary form
            for widget in at.text_input:
                if widget.label == "German word or expression":
                    widget.set_value("sich auf jdn. verlassen")
                elif widget.label == "English meaning":
                    widget.set_value("to rely on someone")
                elif widget.label == "Grammatical information":
                    widget.set_value("reflexive verb + auf (Akk.)")
            add_btn = [b for b in at.button if b.label == "Add to Vocabulary"][0]
            add_btn.click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(db.list_vocabulary(db_path=self.db_path)), 1)

            # Switch to Practice via segmented control
            at.segmented_control[0].set_value("Practice").run()
            self.assertFalse(at.exception)

            # 2. Generate English challenge
            gen_btn = [b for b in at.button if b.label == "Generate English Challenge"][0]
            gen_btn.click().run()
            self.assertFalse(at.exception)

            # Answer must NOT be revealed before submission
            rendered_markdown = "\n".join(m.value for m in at.markdown)
            self.assertIn("rely on my colleagues", rendered_markdown)
            self.assertNotIn("kann ich mich immer auf meine Kollegen verlassen", rendered_markdown)

            # 3. Submit German translation
            at.text_area[0].set_value(
                "Auch wenn es im Büro stressig ist, kann ich mich immer auf meinen Kollegen verlassen."
            )
            submit_btn = [b for b in at.button if b.label == "Check Translation"][0]
            submit_btn.click().run()
            self.assertFalse(at.exception)

            # 4. Feedback is shown & attempt is saved
            rendered_after = "\n".join(m.value for m in at.markdown)
            self.assertIn("Grammar: Errors found", rendered_after)
            self.assertIn("Meaning: Accurate", rendered_after)
            self.assertIn("auf meine Kollegen verlassen", rendered_after)

            # 5. Favorite the sentence
            fav_btn = [b for b in at.button if "Save to Favorites" in b.label][0]
            fav_btn.click().run()
            self.assertFalse(at.exception)

            # 6. Retrieve from Favorites view
            at.segmented_control[0].set_value("Favorites").run()
            self.assertFalse(at.exception)
            fav_markdown = "\n".join(m.value for m in at.markdown)
            self.assertIn("rely on my colleagues", fav_markdown)
            self.assertIn("sich auf jdn. verlassen", fav_markdown)

    def test_save_api_settings_persists_to_dotenv(self) -> None:
        env_file = Path(self.tmp_dir.name) / ".env"
        with patch.dict(os.environ, {}, clear=False):
            saved_path = ai_service.save_api_settings(
                api_key="AIza-test-persisted-key",
                model="gemini-2.5-flash",
                env_path=env_file,
            )
            self.assertEqual(saved_path, env_file)
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("GEMINI_API_KEY", content)
            self.assertIn("AIza-test-persisted-key", content)
            self.assertIn("gemini-2.5-flash", content)
            self.assertEqual(os.environ.get("GEMINI_API_KEY"), "AIza-test-persisted-key")

    def test_gemini_503_falls_back_to_groq(self) -> None:
        class _FailingModels:
            def generate_content(self, **_kwargs):
                raise RuntimeError("503 UNAVAILABLE")

        class _FailingClient:
            def __init__(self, api_key: str) -> None:
                self.models = _FailingModels()

        fake_groq_response = SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"english_prompt":"I can rely on my team.",'
                                '"reference_german":"Ich kann mich auf mein Team verlassen.",'
                                '"context_tag":"workplace",'
                                '"structure_tag":"modal verb"}'
                            )
                        }
                    }
                ]
            },
        )

        with (
            patch.object(ai_service.genai, "Client", _FailingClient),
            patch.object(ai_service.time, "sleep", return_value=None),
            patch.object(ai_service.requests, "post", return_value=fake_groq_response),
        ):
            service = ai_service.get_ai_service(
                api_key="test-gemini-key",
                model="gemini-2.5-flash",
                groq_api_key="test-groq-key",
                groq_model="openai/gpt-oss-120b",
                provider="gemini_first",
            )
            challenge = service.generate_challenge(
                german_expression="sich auf jdn. verlassen",
                english_meaning="to rely on someone",
                grammar_info="reflexive verb + auf (Akk.)",
                level="B1",
            )
            self.assertEqual(challenge.english_prompt, "I can rely on my team.")
            self.assertTrue(service.last_provider_used.startswith("Groq"))

    def test_pwa_end_to_end_and_shared_db_sync(self) -> None:
        pwa_app = pwa_server.create_app(db_path=self.db_path)

        with (
            patch.object(ai_service.genai, "Client", _FakeGenAIClient),
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-key",
                    "GROQ_API_KEY": "",
                    "AI_PROVIDER": "gemini",
                },
            ),
        ):
            client = TestClient(pwa_app)

            # Static PWA shell assets
            self.assertEqual(client.get("/").status_code, 200)
            manifest_resp = client.get("/manifest.json")
            self.assertEqual(manifest_resp.status_code, 200)
            self.assertEqual(manifest_resp.json()["short_name"], "DeutschFlow")
            self.assertEqual(client.get("/sw.js").status_code, 200)
            self.assertEqual(client.get("/static/styles.css").status_code, 200)
            self.assertEqual(client.get("/static/app.js").status_code, 200)
            self.assertEqual(client.get("/static/icon-192.png").status_code, 200)

            # Settings endpoint must never expose raw secret keys
            settings_resp = client.get("/api/settings")
            self.assertEqual(settings_resp.status_code, 200)
            self.assertNotIn("test-key", settings_resp.text)

            # 1. Phone adds vocab via PWA -> synced to shared SQLite DB
            created = client.post(
                "/api/vocab",
                json={
                    "german": "sich auf jdn. verlassen",
                    "english": "to rely on someone",
                    "grammar_info": "reflexive verb + auf (Akk.)",
                    "level": "B1",
                },
            )
            self.assertEqual(created.status_code, 201)
            vocab_id = created.json()["item"]["id"]
            self.assertEqual(len(db.list_vocabulary(db_path=self.db_path)), 1)

            # 2. Laptop (db.py / Streamlit) adds vocab -> immediately visible in PWA
            db.add_vocabulary(
                german="allerdings",
                english="however, though",
                grammar_info="adverb",
                level="B1",
                db_path=self.db_path,
            )
            list_resp = client.get("/api/vocab")
            self.assertEqual(list_resp.status_code, 200)
            self.assertEqual(len(list_resp.json()["items"]), 2)

            # 3. Generate challenge via PWA (reference_german MUST NOT leak before submission)
            gen_resp = client.post("/api/practice/generate", json={"vocab_id": vocab_id})
            self.assertEqual(gen_resp.status_code, 201)
            sentence = gen_resp.json()["sentence"]
            self.assertIn("rely on my colleagues", sentence["english_prompt"])
            self.assertNotIn("reference_german", sentence)

            # 4. Submit translation & receive feedback + save attempt
            sub_resp = client.post(
                "/api/practice/submit",
                json={
                    "sentence_id": sentence["id"],
                    "user_translation": "Auch wenn es im Büro stressig ist, kann ich mich immer auf meinen Kollegen verlassen.",
                },
            )
            self.assertEqual(sub_resp.status_code, 200)
            sub_data = sub_resp.json()
            self.assertTrue(sub_data["evaluation"]["semantic_accurate"])
            self.assertIn("reference_german", sub_data)
            self.assertEqual(len(db.list_attempts_for_sentence(sentence["id"], db_path=self.db_path)), 1)

            # 5. Favorite sentence & retrieve from Favorites
            fav_resp = client.post(
                f"/api/sentences/{sentence['id']}/favorite",
                json={"is_favorite": True},
            )
            self.assertEqual(fav_resp.status_code, 200)
            self.assertTrue(fav_resp.json()["is_favorite"])

            favs = client.get("/api/favorites?level=B1")
            self.assertEqual(favs.status_code, 200)
            self.assertEqual(len(favs.json()["items"]), 1)
            self.assertEqual(favs.json()["items"][0]["id"], sentence["id"])
            self.assertIsNotNone(favs.json()["items"][0]["latest_attempt"])

            # 6. Practice Again endpoint must NOT expose reference_german
            repractice = client.get(f"/api/sentences/{sentence['id']}")
            self.assertEqual(repractice.status_code, 200)
            self.assertNotIn("reference_german", repractice.json()["sentence"])



if __name__ == "__main__":
    unittest.main()
