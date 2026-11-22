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
TTL = "1800s"  # a push that could not be delivered for half an hour is not worth delivering


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


def main(changes_path: str) -> int:
    raw = os.environ.get("FCM_SERVICE_ACCOUNT", "").strip()
    with open(changes_path, encoding="utf-8") as f:
        changes = json.load(f)
    if not raw:
        print("no FCM_SERVICE_ACCOUNT: nothing to send", file=sys.stderr)
        return 0
    if not changes:
        print("nothing changed", file=sys.stderr)
        return 0
    account = json.loads(raw)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    token, failed = access_token(account), 0
    for region, queues in changes.items():
        for queue in queues:
            try:
                send(account["project_id"], token, message(region, queue, stamp))
            except (RuntimeError, OSError) as e:
                failed += 1
                print(f"{topic(region, queue)}: {e}", file=sys.stderr)
    print(f"sent {sum(len(q) for q in changes.values()) - failed}, failed {failed}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
