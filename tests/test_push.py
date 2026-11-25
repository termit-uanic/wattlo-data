import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from collector import build, push


def doc(**days):
    """days: {"2026-11-21": {"1.1": "..."}}"""
    return {"queues": ["1.1", "1.2"], "days": days}


class Changes(unittest.TestCase):
    def test_no_previous_file_wakes_nobody(self):
        self.assertEqual(build.changed_queues(None, doc(a={"1.1": "0", "1.2": "0"})), [])

    def test_only_the_changed_queue(self):
        old = doc(a={"1.1": "0", "1.2": "0"})
        new = doc(a={"1.1": "1", "1.2": "0"})
        self.assertEqual(build.changed_queues(old, new), ["1.1"])

    def test_a_new_day_is_a_change_for_its_queues(self):
        old = doc(a={"1.1": "0", "1.2": "0"})
        new = doc(a={"1.1": "0", "1.2": "0"}, b={"1.1": "0", "1.2": "1"})
        self.assertEqual(build.changed_queues(old, new), ["1.1", "1.2"])

    def test_a_dropped_old_day_is_not_a_change(self):
        old = doc(a={"1.1": "0", "1.2": "0"}, b={"1.1": "1", "1.2": "1"})
        new = doc(b={"1.1": "1", "1.2": "1"})
        self.assertEqual(build.changed_queues(old, new), [])


class Message(unittest.TestCase):
    def test_topic_and_payload(self):
        m = push.message("poltavska-oblast", "1.1", "2026-11-22T10:00:00Z")["message"]
        self.assertEqual(m["topic"], "poltavska-oblast_1.1")
        self.assertEqual(m["data"], {"region": "poltavska-oblast", "queue": "1.1", "updatedAt": "2026-11-22T10:00:00Z"})
        self.assertEqual(m["android"]["priority"], "HIGH")
        self.assertNotIn("notification", m)  # data only: the app writes the text itself

    def test_topics_use_allowed_characters(self):
        import re
        from collector import regions
        for r in regions.REGIONS:
            for q in r.queues:
                self.assertRegex(push.topic(r.slug, q), r"^[a-zA-Z0-9\-_.~%]+$")

    def test_nothing_is_sent_without_the_key(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump({"x": ["1.1"]}, f)
            f.flush()
            with mock.patch.dict(os.environ, {"FCM_SERVICE_ACCOUNT": ""}), \
                    mock.patch("collector.push.send") as send:
                self.assertEqual(push.main(f.name), 0)
                send.assert_not_called()


class DocTime(unittest.TestCase):
    def test_the_push_carries_the_time_of_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "poltavska-oblast.json"), "w", encoding="utf-8") as f:
                json.dump({"updatedAt": "2026-11-25T05:28:43Z"}, f)
            self.assertEqual(push.doc_updated_at("poltavska-oblast", "now", d), "2026-11-25T05:28:43Z")

    def test_without_the_file_the_send_time_is_used(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(push.doc_updated_at("poltavska-oblast", "now", d), "now")
            with open(os.path.join(d, "x.json"), "w", encoding="utf-8") as f:
                f.write("{broken")
            self.assertEqual(push.doc_updated_at("x", "now", d), "now")


class Pending(unittest.TestCase):
    def test_merge_keeps_recent_failures_and_drops_old_ones(self):
        now = 100000
        pending = {"a/1.1": now - 60, "b/2.1": now - push.PENDING_MAX_AGE - 1}
        todo = push.merge({"c": ["1.2"]}, pending, now)
        self.assertEqual(sorted(todo), ["a/1.1", "c/1.2"])

    def run_main(self, send_effect, pending=None):
        with tempfile.TemporaryDirectory() as d:
            changes, pend = os.path.join(d, "c.json"), os.path.join(d, "p.json")
            json.dump({"lvivska-oblast": ["1.1"]}, open(changes, "w"))
            if pending:
                json.dump(pending, open(pend, "w"))
            env = {"FCM_SERVICE_ACCOUNT": json.dumps({"project_id": "x"})}
            with mock.patch.dict(os.environ, env), mock.patch("collector.push.access_token", return_value="t"), \
                    mock.patch("collector.push.send", side_effect=send_effect) as send:
                code = push.main(changes, pend)
            return code, push.load_pending(pend), send.call_count

    def test_a_failed_push_waits_for_the_next_run(self):
        code, left, _ = self.run_main(RuntimeError("boom"))
        self.assertEqual(code, 1)
        self.assertEqual(list(left), ["lvivska-oblast/1.1"])

    def test_a_pending_push_is_sent_and_forgotten(self):
        code, left, calls = self.run_main(None, pending={"poltavska-oblast/2.1": int(__import__("time").time()) - 60})
        self.assertEqual((code, left, calls), (0, {}, 2))


class Signing(unittest.TestCase):
    def test_the_jwt_signature_verifies(self):
        with tempfile.TemporaryDirectory() as d:
            key = os.path.join(d, "k.pem")
            subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
            pub = os.path.join(d, "p.pem")
            subprocess.run(["openssl", "rsa", "-in", key, "-pubout", "-out", pub], check=True, capture_output=True)
            account = {"client_email": "a@b", "token_uri": "https://example.invalid/token",
                       "private_key": open(key).read()}
            jwt = push.signed_jwt(account, 1000)
            head, claims, sig = jwt.split(".")
            pad = lambda s: s + "=" * (-len(s) % 4)
            import base64
            self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(claims)))["scope"], push.SCOPE)
            sigfile = os.path.join(d, "s.bin")
            open(sigfile, "wb").write(base64.urlsafe_b64decode(pad(sig)))
            r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub, "-signature", sigfile],
                               input=f"{head}.{claims}".encode(), capture_output=True)
            self.assertIn(b"Verified OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
