import json
import unittest
from pathlib import Path

from cloud_agent.config import Config, parse_env_file

from tests.helpers import ROOT, make_config, temp_dir


class ConfigTests(unittest.TestCase):
    def test_env_file_parsing(self):
        directory = temp_dir(self)
        path = Path(directory) / "cloud-agent.env"
        path.write_text(
            "# comment\n"
            "CLOUD_AGENT_LLM_MODEL=model-a\n"
            "export CLOUD_AGENT_LLM_BASE_URL='https://example.test/v1'\n"
            "CLOUD_AGENT_LLM_API_KEY=\"quoted-secret\"\n"
            "BROKEN LINE\n",
            encoding="utf-8",
        )
        values, errors = parse_env_file(path)
        self.assertEqual(values["CLOUD_AGENT_LLM_MODEL"], "model-a")
        self.assertEqual(values["CLOUD_AGENT_LLM_BASE_URL"], "https://example.test/v1")
        self.assertEqual(values["CLOUD_AGENT_LLM_API_KEY"], "quoted-secret")
        self.assertEqual(len(errors), 1)
        self.assertIn("缺少", errors[0])

    def test_configured_from_environment(self):
        directory = temp_dir(self)
        config = make_config(directory)
        self.assertTrue(config.configured)
        self.assertEqual(config.model, "test-model")
        self.assertEqual(config.missing_fields, [])
        self.assertEqual(config.llm_proxy, "direct")
        self.assertEqual(config.public_status()["proxy_mode"], "direct")

    def test_proxy_can_be_environment_or_custom(self):
        directory = temp_dir(self)
        env_config = make_config(directory, CLOUD_AGENT_LLM_PROXY="env")
        self.assertEqual(env_config.public_status()["proxy_mode"], "env")
        custom_config = make_config(directory, CLOUD_AGENT_LLM_PROXY="http://127.0.0.1:7890")
        self.assertEqual(custom_config.public_status()["proxy_mode"], "custom")

    def test_unconfigured_is_not_fake_configured(self):
        directory = temp_dir(self)
        config = make_config(directory, configured=False)
        self.assertFalse(config.configured)
        self.assertEqual(
            config.missing_fields,
            [
                "CLOUD_AGENT_LLM_BASE_URL",
                "CLOUD_AGENT_LLM_MODEL",
                "CLOUD_AGENT_LLM_API_KEY",
            ],
        )

    def test_public_status_does_not_contain_secret(self):
        directory = temp_dir(self)
        config = make_config(directory)
        serialized = json.dumps(config.public_status(), ensure_ascii=False)
        self.assertNotIn("test-secret-key", serialized)
        self.assertNotIn("test-secret-key", repr(config))

    def test_default_port_matches_service_contract(self):
        config = Config.load(root=ROOT, environ={}, allow_default_env_file=False)
        self.assertEqual(config.port, 8130)

    def test_key_file_is_supported(self):
        directory = temp_dir(self)
        key_path = Path(directory) / "llm.key"
        key_path.write_text("file-secret-key\n", encoding="utf-8")
        env_file = Path(directory) / "cloud-agent.env"
        env_file.write_text(
            "CLOUD_AGENT_LLM_BASE_URL=https://example.test/v1\n"
            "CLOUD_AGENT_LLM_MODEL=model-b\n"
            "CLOUD_AGENT_LLM_API_KEY_FILE=%s\n" % key_path,
            encoding="utf-8",
        )
        config = Config.load(
            root=ROOT,
            environ={
                "CLOUD_AGENT_ENV_FILE": str(env_file),
                "CLOUD_AGENT_STATE_DIR": str(Path(directory) / "state"),
            },
            allow_default_env_file=False,
        )
        self.assertTrue(config.configured)
        self.assertEqual(config.api_key_source, "file")
        self.assertEqual(config.api_key, "file-secret-key")

    def test_key_file_wins_over_legacy_direct_key(self):
        directory = temp_dir(self)
        key_path = Path(directory) / "deepseek.key"
        key_path.write_text("file-secret-key\n", encoding="utf-8")
        env_file = Path(directory) / "cloud-agent.env"
        env_file.write_text(
            "CLOUD_AGENT_LLM_BASE_URL=https://api.deepseek.com\n"
            "CLOUD_AGENT_LLM_MODEL=deepseek-v4-flash\n"
            "CLOUD_AGENT_LLM_API_KEY_FILE=%s\n" % key_path,
            encoding="utf-8",
        )
        for legacy in ("", "stale-legacy-key"):
            config = Config.load(
                root=ROOT,
                environ={
                    "CLOUD_AGENT_ENV_FILE": str(env_file),
                    "CLOUD_AGENT_STATE_DIR": str(Path(directory) / "state"),
                    "CLOUD_AGENT_LLM_API_KEY": legacy,
                },
                allow_default_env_file=False,
            )
            self.assertTrue(config.configured, legacy)
            self.assertEqual(config.api_key, "file-secret-key")
            self.assertEqual(config.api_key_source, "file")

    def test_missing_explicit_env_file_blocks_configuration(self):
        directory = temp_dir(self)
        config = Config.load(
            root=ROOT,
            environ={
                "CLOUD_AGENT_ENV_FILE": str(Path(directory) / "missing.env"),
                "CLOUD_AGENT_LLM_BASE_URL": "https://example.test/v1",
                "CLOUD_AGENT_LLM_MODEL": "model",
                "CLOUD_AGENT_LLM_API_KEY": "key",
            },
            allow_default_env_file=False,
        )
        self.assertFalse(config.configured)
        self.assertTrue(config.config_errors)


if __name__ == "__main__":
    unittest.main()
