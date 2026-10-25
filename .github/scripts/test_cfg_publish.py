import copy
import hashlib
import json
import unittest
from cfg_publish import MARKER, parse_submission, publish, refresh_counts, validate_config, reconcile


def body(config="[ESP]\nEnabled=1\n", **extra):
    payload = {"schema": 1, "name": "Crimson Legit", "description": "A clean preset", "config": config}
    payload.update(extra)
    return MARKER + "\n```json\n" + json.dumps(payload) + "\n```"


class FakeGitHub:
    repository = "Vanta-exe/cfg"

    def __init__(self):
        self.commits = []
        self.calls = []
        self.releases = []
        self.issues = []

    def path(self, suffix):
        return "/repos/" + self.repository + suffix

    def release_asset(self, issue, content):
        return 100, 200, 42, hashlib.sha256(content).hexdigest()

    def commit(self, files, message):
        self.commits.append((copy.deepcopy(files), message))

    def call(self, method, path, data=None, **kwargs):
        self.calls.append((method, path, data))
        return self.issues if "/issues?" in path else self.releases


class ConfigTests(unittest.TestCase):
    def test_roundtrip(self):
        data = parse_submission(body())
        self.assertEqual(data["config"], "[ESP]\nEnabled=1\n")

    def test_extended_numeric_fields(self):
        self.assertEqual(validate_config("[Aim]\nHeadOffsetZ=-1.5\n"), "[Aim]\nHeadOffsetZ=-1.5\n")

    def test_rejects_executable_and_secret_sections(self):
        for section in ("Offsets", "Patterns", "License", "GitHub", "GUI"):
            with self.subTest(section=section), self.assertRaises(ValueError):
                parse_submission(body("[" + section + "]\nEnabled=1\n"))

    def test_rejects_protection_and_exit_key_changes(self):
        for key in ("CaptureProtection", "InputReconstruction", "Menu", "Stop", "MenuHold", "StopHold"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config("[Keys]\n" + key + "=0\n")

    def test_rejects_duplicate_injection(self):
        for config in ("[ESP]\nEnabled=1\nenabled=0\n", "[ESP]\nEnabled=1\n[esp]\nEnabled=0\n"):
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_rejects_non_numeric(self):
        for value in ("nan", "inf", "1; run", "$(touch /tmp/a)", "0xDEADBEEF", "1e99", "https://evil"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_config("[ESP]\nEnabled=" + value + "\n")

    def test_limits(self):
        for text in ("", "x" * 50000):
            with self.assertRaises(ValueError):
                validate_config(text)
        for name in ("../bad", "CON/evil", " leading", "a\nname", "x" * 81):
            with self.assertRaises(ValueError):
                parse_submission(body(name=name))

    def test_unicode_names(self):
        self.assertEqual(parse_submission(body(name="Kırmızı ayarlar"))["name"], "Kırmızı ayarlar")


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.catalog = {"schema": 1, "repository": self.github.repository, "profiles": []}
        self.issue = {"number": 12, "user": {"login": "real-author"}, "state": "open", "body": body(),
                      "created_at": "2026-10-25T00:00:00Z", "updated_at": "2026-10-25T01:00:00Z"}

    def test_publish_atomically_records_all_files(self):
        self.assertTrue(publish(self.github, self.issue, self.catalog))
        files, _ = self.github.commits[-1]
        self.assertEqual(set(files), {"configs/12/config.ini", "configs/12/metadata.json", "catalog.json"})
        record = self.catalog["profiles"][0]
        self.assertEqual(record["author"], "real-author")
        self.assertEqual(record["downloads"], 42)

    def test_edits_do_not_duplicate_identity(self):
        publish(self.github, self.issue, self.catalog)
        self.issue["body"] = body(name="Updated title")
        publish(self.github, self.issue, self.catalog)
        self.assertEqual(len(self.catalog["profiles"]), 1)
        self.assertEqual(self.catalog["profiles"][0]["name"], "Updated title")

    def test_author_is_not_taken_from_body(self):
        self.issue["body"] = body(author="administrator")
        publish(self.github, self.issue, self.catalog)
        self.assertEqual(self.catalog["profiles"][0]["author"], "real-author")

    def test_owner_mismatch_rejected(self):
        publish(self.github, self.issue, self.catalog)
        self.issue["user"]["login"] = "attacker"
        with self.assertRaises(ValueError):
            publish(self.github, self.issue, self.catalog)

    def test_closed_issue_unlists_but_keeps_history(self):
        publish(self.github, self.issue, self.catalog)
        self.issue["state"] = "closed"
        publish(self.github, self.issue, self.catalog)
        self.assertEqual(self.catalog["profiles"], [])
        self.assertEqual(set(self.github.commits[-1][0]), {"catalog.json"})

    def test_stats_count_all_immutable_revisions(self):
        publish(self.github, self.issue, self.catalog)
        self.github.releases = [{"id": 100, "assets": [{"name": "old.ini", "download_count": 30},
                                                      {"name": "new.ini", "download_count": 20}]}]
        refresh_counts(self.github, self.catalog)
        self.assertEqual(self.catalog["profiles"][0]["downloads"], 50)

    def test_invalid_data_never_reaches_git(self):
        self.issue["body"] = body("[License]\nKey=123\n")
        with self.assertRaises(ValueError):
            publish(self.github, self.issue, self.catalog)
        self.assertEqual(self.github.commits, [])

    def test_reconcile_recovers_missed_issue_event(self):
        self.github.issues = [self.issue]
        reconcile(self.github, self.catalog)
        self.assertEqual(self.catalog["profiles"][0]["issue"], 12)
        before = len(self.github.commits)
        reconcile(self.github, self.catalog)
        self.assertEqual(len(self.github.commits), before)

    def test_reconcile_unlists_closed_and_skips_bad_submissions(self):
        publish(self.github, self.issue, self.catalog)
        self.issue.update(state="closed", body=None)
        self.github.issues = [self.issue, dict(self.issue, number=13, state="open", body=body("[GUI]\nX=1\n"))]
        reconcile(self.github, self.catalog)
        self.assertEqual(self.catalog["profiles"], [])


if __name__ == "__main__":
    unittest.main()
