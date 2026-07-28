import json
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.build_info import (
    API_SCHEMA_VERSION,
    BUILD_INPUTS,
)
from app.local_web_app import (
    ASSETS_DIR,
    STATIC_ASSETS_DIR,
    create_app,
)
from tests.visual_baseline_app import VisualBaselineService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
PRODUCTION_DIST_DIR = PROJECT_ROOT / "web-dist"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_frontend.ps1"


class ProductionFrontendContractTests(unittest.TestCase):
    def test_production_background_uses_default_canvas_gradients(self) -> None:
        source_styles = (FRONTEND_DIR / "src" / "styles.css").read_text(
            encoding="utf-8",
        )
        built_styles = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PRODUCTION_DIST_DIR / "assets").glob("index-*.css")
        )

        self.assertIn("radial-gradient(circle at 0 0", source_styles)
        self.assertIn("radial-gradient(circle at 100% 12%", source_styles)
        self.assertNotIn('url("/assets/app-background.avif")', source_styles)
        self.assertIn("radial-gradient(circle at 0 0", built_styles)
        self.assertNotIn("app-background.avif", built_styles)

    def test_vue_toolchain_and_distribution_are_production_contract(self) -> None:
        package_json = json.loads(
            (FRONTEND_DIR / "package.json").read_text(encoding="utf-8"),
        )

        self.assertTrue(
            {
                "dev",
                "typecheck",
                "build",
                "test:unit",
                "test:coverage",
                "test:e2e",
                "lint",
            }.issubset(package_json["scripts"]),
        )
        self.assertTrue(
            {"vue", "pinia"}.issubset(package_json["dependencies"]),
        )
        self.assertTrue(
            {
                "@vitejs/plugin-vue",
                "typescript",
                "vite",
                "vitest",
                "vue-tsc",
            }.issubset(package_json["devDependencies"]),
        )

        self.assertEqual(ASSETS_DIR, PRODUCTION_DIST_DIR)
        self.assertEqual(STATIC_ASSETS_DIR, PRODUCTION_DIST_DIR / "assets")
        self.assertIn("web-dist", BUILD_INPUTS)
        self.assertFalse(any(path.startswith("web/") for path in BUILD_INPUTS))
        self.assertTrue((FRONTEND_DIR / "package-lock.json").is_file())
        self.assertTrue((FRONTEND_DIR / "vite.config.ts").is_file())
        self.assertTrue((FRONTEND_DIR / "tsconfig.json").is_file())
        self.assertTrue((PRODUCTION_DIST_DIR / "index.html").is_file())
        self.assertEqual(list(PRODUCTION_DIST_DIR.rglob("*.map")), [])

    def test_production_assets_are_vue_after_cutover(self) -> None:
        service = VisualBaselineService()
        client = TestClient(
            create_app(service=service),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51000),
        )
        self.addCleanup(client.close)

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('<div id="app"></div>', response.text)
        self.assertNotIn('id="account-grid"', response.text)
        self.assertIn('src="/assets/theme-init.js"', response.text)

    def test_production_frontend_has_a_reproducible_build_entrypoint(
        self,
    ) -> None:
        script = BUILD_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("npm ci", script)
        self.assertIn("npm run build", script)
        self.assertIn("web-dist", script)
        self.assertIn("*.map", script)

    def test_production_dist_is_csp_safe_and_served_by_fastapi(self) -> None:
        service = VisualBaselineService()
        client = TestClient(
            create_app(
                service=service,
                assets_dir=PRODUCTION_DIST_DIR,
                static_assets_dir=PRODUCTION_DIST_DIR / "assets",
            ),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51000),
        )
        self.addCleanup(client.close)

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('<div id="app"></div>', response.text)
        self.assertNotIn('id="account-grid"', response.text)
        self.assertIn('src="/assets/theme-init.js"', response.text)
        self.assertLess(
            response.text.index('src="/assets/theme-init.js"'),
            response.text.index('type="module"'),
        )
        self.assertNotRegex(
            response.text,
            r"<script(?![^>]*\bsrc=)[^>]*>",
        )
        self.assertNotIn("<style", response.text)
        self.assertNotIn("unsafe-inline", response.headers["content-security-policy"])
        self.assertNotIn("unsafe-eval", response.headers["content-security-policy"])
        self.assertNotIn("/assets/assets/", response.text)

        asset_paths = re.findall(
            r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"',
            response.text,
        )
        self.assertGreaterEqual(len(asset_paths), 2)
        hashed_assets = [
            path
            for path in asset_paths
            if re.search(r"-[A-Za-z0-9_-]{8,}\.(?:js|css)$", path)
        ]
        self.assertTrue(any(path.endswith(".js") for path in hashed_assets))
        self.assertTrue(any(path.endswith(".css") for path in hashed_assets))
        for asset_path in asset_paths:
            asset_response = client.get(asset_path)
            self.assertEqual(asset_response.status_code, 200, asset_path)
            expected_content_type = (
                "javascript"
                if asset_path.endswith(".js")
                else "text/css"
            )
            self.assertIn(
                expected_content_type,
                asset_response.headers["content-type"],
            )

        theme_script = client.get("/assets/theme-init.js")
        self.assertEqual(theme_script.status_code, 200)
        self.assertIn("otp-codex-theme", theme_script.text)
        self.assertIn("#dfe4eb", theme_script.text)

    def test_production_api_contract_remains_authenticated(self) -> None:
        service = VisualBaselineService()
        client = TestClient(
            create_app(
                service=service,
                assets_dir=PRODUCTION_DIST_DIR,
                static_assets_dir=PRODUCTION_DIST_DIR / "assets",
            ),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 51000),
        )
        self.addCleanup(client.close)

        unauthenticated = client.get("/api/bootstrap")
        authenticated = client.get(
            "/api/bootstrap",
            headers={
                "Authorization": (
                    f"Bearer {service.access_token}"
                ),
            },
        )

        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(authenticated.status_code, 200)
        self.assertEqual(
            authenticated.json()["api_schema_version"],
            API_SCHEMA_VERSION,
        )

    def test_production_mode_fails_fast_when_build_is_missing(self) -> None:
        missing = PROJECT_ROOT / "missing-production-dist"

        with self.assertRaisesRegex(
            FileNotFoundError,
            "Production frontend build is incomplete",
        ):
            create_app(
                service=VisualBaselineService(),
                assets_dir=missing,
                static_assets_dir=missing / "assets",
            )

    def test_production_mode_fails_fast_when_referenced_asset_is_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            production_dir = Path(temp_dir)
            static_dir = production_dir / "assets"
            static_dir.mkdir()
            (production_dir / "index.html").write_text(
                (
                    '<div id="app"></div>'
                    '<script src="/assets/missing-entry.js"></script>'
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                FileNotFoundError,
                "missing-entry.js",
            ):
                create_app(
                    service=VisualBaselineService(),
                    assets_dir=production_dir,
                    static_assets_dir=static_dir,
                )
