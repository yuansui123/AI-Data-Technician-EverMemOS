from __future__ import annotations

import importlib
import sys
import types
import unittest

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))
_config = importlib.import_module("config")
validate_sandbox_backend = _config.validate_sandbox_backend


class SandboxConfigValidationTests(unittest.TestCase):
    def test_validate_sandbox_backend_accepts_supported_values(self) -> None:
        self.assertEqual(validate_sandbox_backend("local"), "local")
        self.assertEqual(validate_sandbox_backend("docker"), "docker")

    def test_validate_sandbox_backend_rejects_unknown_value(self) -> None:
        with self.assertRaises(ValueError):
            validate_sandbox_backend("podman")


if __name__ == "__main__":
    unittest.main()
