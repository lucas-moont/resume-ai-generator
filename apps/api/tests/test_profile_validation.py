import unittest

from app.models import ProfileMaster
from app.services.projects_loader import looks_like_placeholder_profile


class ProfileValidationTests(unittest.TestCase):
    def test_detects_placeholder_profile(self) -> None:
        profile = ProfileMaster(
            fullName="Alex Sample",
            headline="Full Stack Developer",
            summary="Developer focused on web products. Replace this text with your real summary.",
        )
        self.assertTrue(looks_like_placeholder_profile(profile))

    def test_accepts_real_profile(self) -> None:
        profile = ProfileMaster(
            fullName="Kevvan Silva",
            headline="Senior Fullstack Developer",
            summary="Senior engineer focused on Node.js, TypeScript, and platform architecture.",
        )
        self.assertFalse(looks_like_placeholder_profile(profile))


if __name__ == "__main__":
    unittest.main()
