import unittest
from types import SimpleNamespace

from sqlmodel import text
from sqlmodel.pool import StaticPool

from app.db.engine import create_db_engine, init_db
from app.routers import deps


class MainModelSelectionTests(unittest.TestCase):
    def test_resolve_requested_model_returns_none_for_empty_values(self) -> None:
        self.assertIsNone(deps.resolve_requested_model(None))
        self.assertIsNone(deps.resolve_requested_model(""))
        self.assertIsNone(deps.resolve_requested_model("   "))

    def test_resolve_requested_model_returns_trimmed_model(self) -> None:
        self.assertEqual(deps.resolve_requested_model(" gemini-2.5-flash "), "gemini-2.5-flash")


class GetSessionDependencyTests(unittest.TestCase):
    """No route calls Depends(get_session) yet (B6's chat routes are the first consumer),
    so this is the only coverage the function has -- a fake Request whose only requirement
    is the request.app.state.db_engine attribute path get_session actually reads."""

    def test_yields_a_working_session_bound_to_the_request_app_engine(self) -> None:
        engine = create_db_engine("sqlite://", poolclass=StaticPool)
        init_db(engine)
        fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_engine=engine)))

        gen = deps.get_session(fake_request)
        session = next(gen)
        try:
            result = session.exec(text("SELECT 1")).first()
            self.assertEqual(result[0], 1)
        finally:
            gen.close()


if __name__ == "__main__":
    unittest.main()
