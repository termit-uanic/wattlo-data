"""python -m collector.push CHANGES_JSON: tells the apps that schedules changed (Firebase Cloud Messaging topics).

One data-only message per changed queue, to the topic "<region>_<queue>" (for example "poltavska-oblast_1.1"); the app
wakes up and loads the file itself. The service account key comes from the environment (FCM_SERVICE_ACCOUNT, the JSON
text); without it nothing is sent. The token is signed with the openssl command, so there is nothing to install."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TTL = "7200s"  # a watch in Doze takes a push at its next maintenance window, which can be an hour or more away


def topic(region: str, queue: str) -> str:
    return f"{region}_{queue}"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def signed_jwt(account: dict, now: int) -> str:
    head = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = b64(json.dumps({"iss": account["client_email"], "scope": SCOPE, "aud": account["token_uri"],
                             "iat": now, "exp": now + 3000}).encode())
    unsigned = f"{head}.{claims}".encode()
    with tempfile.NamedTemporaryFile("w", suffix=".pem") as key:  # created with the mode 0600
        key.write(account["private_key"])
        key.flush()
        signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key.name], input=unsigned,
                                   capture_output=True, check=True).stdout
    return f"{unsigned.decode()}.{b64(signature)}"


def access_token(account: dict, now: int = None) -> str:
    body = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                   "assertion": signed_jwt(account, now or int(time.time()))}).encode()
    with urllib.request.urlopen(urllib.request.Request(account["token_uri"], data=body), timeout=20) as r:
        return json.load(r)["access_token"]


def message(region: str, queue: str, updated_at: str) -> dict:
    t = topic(region, queue)
    return {"message": {"topic": t,
                        "data": {"region": region, "queue": queue, "updatedAt": updated_at},
                        "android": {"priority": "HIGH", "ttl": TTL, "collapse_key": t}}}


def send(project: str, token: str, body: dict) -> None:
    request = urllib.request.Request(
        f"https://fcm.googleapis.com/v1/projects/{project}/messages:send", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            urllib.request.urlopen(request, timeout=20).read()
            return
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429 or attempt == 2:
                raise RuntimeError(f"FCM answered {e.code}: {e.read()[:200]!r}") from None
        except OSError:
            if attempt == 2:
                raise
        time.sleep(3)


PENDING_MAX_AGE = 3 * 3600  # an app polls anyway: an older push is not worth sending


def load_pending(path):
    """{"<region>/<queue>": time of the change (unix seconds)} that could not be sent earlier."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: int(v) for k, v in data.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def merge(changes: dict, pending: dict, now: int) -> dict:
    """The pushes to send now: this run's changes and the earlier ones that failed (not older than PENDING_MAX_AGE)."""
    todo = {k: t for k, t in pending.items() if now - t <= PENDING_MAX_AGE}
    for region, queues in changes.items():
        for queue in queues:
            todo[f"{region}/{queue}"] = now
    return todo


def save_pending(path, failed: dict) -> None:
    """Writes what is still unsent, or removes the file when everything went out."""
    if failed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(failed, f, sort_keys=True, indent=1)
            f.write("\n")
    elif os.path.exists(path):
        os.remove(path)


def main(changes_path: str, pending_path: str = None) -> int:
    raw = os.environ.get("FCM_SERVICE_ACCOUNT", "").strip()
    with open(changes_path, encoding="utf-8") as f:
        changes = json.load(f)
    if not raw:
        print("no FCM_SERVICE_ACCOUNT: nothing to send", file=sys.stderr)
        return 0
    now = int(time.time())
    todo = merge(changes, load_pending(pending_path) if pending_path else {}, now)
    if not todo:
        print("nothing to send", file=sys.stderr)
        return 0
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    failed = {}
    try:
        account = json.loads(raw)
        token = access_token(account)
    except Exception as e:  # no token: nothing can be sent now, everything waits for the next run
        print(f"no access token: {e}", file=sys.stderr)
        failed = dict(todo)
    else:
        for key, changed_at in todo.items():
            region, queue = key.split("/", 1)
            try:
                send(account["project_id"], token, message(region, queue, stamp))
            except (RuntimeError, OSError) as e:
                failed[key] = changed_at
                print(f"{topic(region, queue)}: {e}", file=sys.stderr)
    if pending_path:
        save_pending(pending_path, failed)
    print(f"sent {len(todo) - len(failed)}, failed {len(failed)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
