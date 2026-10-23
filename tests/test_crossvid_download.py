"""Small offline checks for the deleted CrossVid media recovery contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import prepare_crossvid_data as preparation


class CrossVidDownloadTests(unittest.TestCase):
    def test_recovery_requires_exact_files_and_content(self):
        data = b"tiny test video"
        entry = SimpleNamespace(path="videos/behavior/example.mp4", size=len(data),
                                lfs=SimpleNamespace(sha256=hashlib.sha256(data).hexdigest()))
        with patch.object(preparation, "BEHAVIOR_COUNT", 1), tempfile.TemporaryDirectory() as directory:
            inventory = preparation.behavior_inventory([entry])
            root = Path(directory)
            media = root / entry.path
            media.parent.mkdir(parents=True)
            media.write_bytes(data)
            (root / "QA").mkdir()
            qa = root / "QA/BU.json"
            qa.write_text(json.dumps([{"videos": ["behavior/example.mp4"]}]))
            preparation.verify_behavior(root, inventory)
            media.write_bytes(b"X" * len(data))
            with self.assertRaisesRegex(ValueError, "SHA256"):
                preparation.verify_behavior(root, inventory)
            media.write_bytes(data)
            qa.write_text(json.dumps([{"videos": ["behavior/missing.mp4"]}]))
            with self.assertRaisesRegex(ValueError, "unverified"):
                preparation.verify_behavior(root, inventory)
            with self.assertRaisesRegex(ValueError, "unique"):
                preparation.behavior_inventory([entry, entry])
            entry.path = "videos/behavior/../../unexpected.mp4"
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                preparation.behavior_inventory([entry])


if __name__ == "__main__":
    unittest.main()
