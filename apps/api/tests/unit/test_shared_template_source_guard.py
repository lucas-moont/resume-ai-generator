"""Guards packages/resume-templates/ as the ONE physical source both apps
consume — not a copy that can silently drift.

apps/api resolves it via RESUME_TEMPLATES_PACKAGE_DIR (a relative filesystem
path from pdf_export.py). apps/web resolves the same directory two ways: the
Vite `@resume-templates` alias (resume.css, at runtime) and the TS
`@resume-templates/*` path mapping (templates.json, for `tsc -b` and the
editor). This test computes the repo root independently (from this file's own
location, not by reusing pdf_export's path math) and checks all three
resolve to the identical directory, plus that there is exactly one
resume.css/templates.json pair in the repo.
"""

import re
import unittest
from pathlib import Path

from app.services.pdf_export import RESUME_TEMPLATES_PACKAGE_DIR

# apps/api/tests/unit/test_shared_template_source_guard.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]


class SharedTemplateSourceGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(
            (_REPO_ROOT / "CLAUDE.md").is_file(),
            f"{_REPO_ROOT} doesn't look like the repo root (no CLAUDE.md)",
        )

    def test_api_path_resolves_to_the_canonical_package_dir(self) -> None:
        canonical = _REPO_ROOT / "packages" / "resume-templates"
        self.assertEqual(RESUME_TEMPLATES_PACKAGE_DIR.resolve(), canonical.resolve())

    def test_exactly_one_resume_css_and_templates_json_exist_in_the_repo(self) -> None:
        skip_dirs = {"node_modules", ".venv", ".git", "dist", "build"}

        def find(filename: str) -> list[Path]:
            matches = []
            for path in _REPO_ROOT.rglob(filename):
                if not any(part in skip_dirs for part in path.parts):
                    matches.append(path)
            return matches

        css_matches = find("resume.css")
        manifest_matches = find("templates.json")
        self.assertEqual(
            css_matches,
            [RESUME_TEMPLATES_PACKAGE_DIR / "resume.css"],
            "Found more than one resume.css (or none) outside node_modules/.venv — "
            "it must exist only under packages/resume-templates/",
        )
        self.assertEqual(
            manifest_matches,
            [RESUME_TEMPLATES_PACKAGE_DIR / "templates.json"],
            "Found more than one templates.json (or none) outside node_modules/.venv — "
            "it must exist only under packages/resume-templates/",
        )

    def test_web_vite_alias_points_at_the_same_directory_as_the_api(self) -> None:
        vite_config = (_REPO_ROOT / "apps" / "web" / "vite.config.ts").read_text(encoding="utf-8")
        match = re.search(
            r"resumeTemplatesDir\s*=\s*fileURLToPath\(new URL\('([^']+)',",
            vite_config,
        )
        self.assertIsNotNone(match, "Could not find the @resume-templates alias target in vite.config.ts")
        alias_target = (_REPO_ROOT / "apps" / "web" / match.group(1)).resolve()
        self.assertEqual(alias_target, RESUME_TEMPLATES_PACKAGE_DIR.resolve())

    def test_web_ts_path_mapping_points_at_the_same_directory_as_the_api(self) -> None:
        tsconfig = (_REPO_ROOT / "apps" / "web" / "tsconfig.app.json").read_text(encoding="utf-8")
        match = re.search(
            r'"@resume-templates/\*":\s*\[\s*"([^"]+)/\*"\s*\]',
            tsconfig,
        )
        self.assertIsNotNone(
            match, "Could not find the @resume-templates/* path mapping in tsconfig.app.json"
        )
        mapped_dir = (_REPO_ROOT / "apps" / "web" / match.group(1)).resolve()
        self.assertEqual(mapped_dir, RESUME_TEMPLATES_PACKAGE_DIR.resolve())
