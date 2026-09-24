from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from app.build_info import API_SCHEMA_VERSION
from tests.visual_baseline_app import (
    VISUAL_BASELINE_ACCESS_TOKEN,
    VISUAL_BASELINE_CSRF_TOKEN,
    create_visual_baseline_app,
)


class VisualBaselineFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(
            create_visual_baseline_app(),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51006),
        )
        self.client.headers.update(
            {
                "Authorization": (
                    f"Bearer {VISUAL_BASELINE_ACCESS_TOKEN}"
                ),
                "X-CSRF-Token": VISUAL_BASELINE_CSRF_TOKEN,
            }
        )

    def tearDown(self) -> None:
        self.client.close()

    def test_fixture_bootstrap_is_sanitized_and_contract_valid(self) -> None:
        response = self.client.get("/api/bootstrap")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["api_schema_version"], API_SCHEMA_VERSION)
        self.assertEqual(len(payload["state"]["accounts"]), 3)
        self.assertEqual(
            payload["state"]["accounts"][0]["banked_reset_count"],
            2,
        )
        self.assertEqual(
            payload["state"]["accounts"][0]["plus_expires_at"],
            "2026-10-11",
        )
        self.assertTrue(
            all(
                account["email"].endswith(".test")
                for account in payload["state"]["accounts"]
            )
        )

        serialized_state = json.dumps(payload["state"]).casefold()
        for sensitive_name in (
            "password",
            "secret",
            "access_token",
            "auth.json",
            "profile_dir",
        ):
            self.assertNotIn(sensitive_name, serialized_state)

    def test_fixture_exercises_token_usage_states(self) -> None:
        response = self.client.get("/api/usage/tokens")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(
            {
                account["status"]
                for account in payload["accounts"]
            },
            {"fresh", "stale", "unavailable"},
        )
        self.assertEqual(payload["coverage"]["total_accounts"], 3)

    def test_fixture_supports_sanitized_account_actions_without_file_data(
        self,
    ) -> None:
        account_id = "1111111111111111"
        action_requests = (
            ("post", "/api/codex/refresh", {"account_id": account_id}),
            ("post", f"/api/codex/{account_id}/login", None),
            ("post", f"/api/codex/{account_id}/unlink", None),
            ("delete", f"/api/accounts/{account_id}", None),
        )

        action_payloads = []
        for method, path, body in action_requests:
            response = self.client.request(method, path, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            action_payloads.append(response.json())

        reveal = self.client.post(
            f"/api/accounts/{account_id}/sensitive",
            json={"field": "password"},
        )
        self.assertEqual(reveal.status_code, 200, reveal.text)
        self.assertEqual(reveal.json(), {"value": "fixture-only-value"})

        public_artifacts = json.dumps(
            {
                "state": self.client.get("/api/state").json(),
                "actions": action_payloads,
            }
        ).casefold()
        for sensitive_file in (
            "auth.json",
            "accounts.json",
            ".web_session.json",
            "codex_profiles",
            "profile_dir",
        ):
            self.assertNotIn(sensitive_file, public_artifacts)
        self.assertNotIn("fixture-only-value", public_artifacts)

    def test_fixture_single_account_check_and_add_are_sanitized(
        self,
    ) -> None:
        raw_password = "fixture-password-input"
        raw_secret = "FIXTURE_SECRET_INPUT"
        duplicate = (
            f"alpha@example.test|{raw_password}|{raw_secret}"
        )
        available = (
            f"delta@example.test|{raw_password}|{raw_secret}"
        )

        check_response = self.client.post(
            "/api/accounts/import/check",
            json={"lines": duplicate},
        )
        self.assertEqual(
            check_response.status_code,
            200,
            check_response.text,
        )
        self.assertEqual(
            check_response.json(),
            {
                "valid": False,
                "conflict": "email",
                "message": "Email đã tồn tại.",
            },
        )
        serialized_check = json.dumps(check_response.json())
        self.assertNotIn(raw_password, serialized_check)
        self.assertNotIn(raw_secret, serialized_check)

        add_response = self.client.post(
            "/api/accounts/import",
            json={"lines": available},
        )
        self.assertEqual(
            add_response.status_code,
            200,
            add_response.text,
        )
        self.assertEqual(
            add_response.json(),
            {"total": 4, "email": "delta@example.test"},
        )
        serialized_add = json.dumps(add_response.json())
        self.assertNotIn(raw_password, serialized_add)
        self.assertNotIn(raw_secret, serialized_add)
        preview_response = self.client.post(
            "/api/accounts/import/preview",
            json={"lines": available},
        )
        self.assertEqual(preview_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
