"""An unexpected engine error is kept, with its traceback, in <data>/.logs/engine-errors.log (the packaged app has no
console). The query string is left out: it can carry what the person typed."""
import tempfile
import unittest
from pathlib import Path

from form.server import _log_error


class EngineErrorLog(unittest.TestCase):
    def test_traceback_is_kept_without_the_query(self):
        root = Path(tempfile.mkdtemp())
        try:
            raise ValueError("Error -3 while decompressing data: incorrect header check")
        except ValueError as e:
            _log_error(root, "POST", "/api/start/blank?text=my+secret+words", e)
        log = (root / ".logs" / "engine-errors.log").read_text(encoding="utf-8")
        self.assertIn("POST /api/start/blank\n", log)
        self.assertIn("Traceback", log)
        self.assertIn("incorrect header check", log)
        self.assertNotIn("secret", log)

    def test_never_raises(self):
        _log_error(Path("/nonexistent/\0bad"), "GET", "/x", RuntimeError("x"))     # an unwritable place is ignored


if __name__ == "__main__":
    unittest.main()
