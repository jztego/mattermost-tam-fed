#!/usr/bin/env python3
"""Create the Planet Express workspace: team, LDAP group mention, incoming webhook.

Reads the lab admin password from secrets/admin.env. Talks only to the local server.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "secrets" / "admin.env"
BASE = os.environ.get("MM_URL", "http://127.0.0.1:8065")
DEFAULTS = {
    "MM_URL": BASE,
    "MM_ADMIN_USER": "sysadmin",
    "MM_ADMIN_EMAIL": "sysadmin@planetexpress.test",
    "MM_ADMIN_PASSWORD": "LabAdmin!2026mm",
}


def load_env(path: Path) -> dict:
    if not path.exists():
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.write_text("".join(f"{key}={value}\n" for key, value in DEFAULTS.items()))
        path.chmod(0o600)
        print(f"wrote {path}")
    out = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key] = value
    return out


def decode(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.decode()[:500]


def request(method, path, body=None, token=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            header_token = resp.headers.get("Token")
            parsed = decode(raw)
            return resp.status, parsed, header_token
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, decode(raw), None


def must(status, payload, ok=(200, 201)):
    if status not in ok:
        raise SystemExit(f"HTTP {status}: {payload}")
    return payload


def main():
    global BASE
    env = load_env(ENV)
    BASE = env.get("MM_URL", BASE)
    status, user, token = request(
        "POST",
        "/api/v4/users/login",
        {"login_id": env["MM_ADMIN_USER"], "password": env["MM_ADMIN_PASSWORD"]},
    )
    if status != 200:
        status, created, _ = request(
            "POST",
            "/api/v4/users",
            {
                "email": env["MM_ADMIN_EMAIL"],
                "username": env["MM_ADMIN_USER"],
                "password": env["MM_ADMIN_PASSWORD"],
            },
        )
        if status not in (200, 201):
            raise SystemExit(f"create admin HTTP {status}: {created}")
        status, user, token = request(
            "POST",
            "/api/v4/users/login",
            {"login_id": env["MM_ADMIN_USER"], "password": env["MM_ADMIN_PASSWORD"]},
        )
    must(status, user)
    print(f"admin {user['username']} {user['id']}")

    status, cfg, _ = request("GET", "/api/v4/config", token=token)
    ldap = must(status, cfg)["LdapSettings"]
    print(
        "ldap",
        f"enable={ldap.get('Enable')}",
        f"server={ldap.get('LdapServer')}:{ldap.get('LdapPort')}",
        f"group_filter={ldap.get('GroupFilter')}",
    )

    status, test, _ = request("POST", "/api/v4/ldap/test", token=token)
    print(f"ldap test HTTP {status}: {test if status != 200 else 'ok'}")

    status, teams, _ = request("GET", "/api/v4/teams", token=token)
    must(status, teams)
    team = next((item for item in teams if item["name"] == "planet-express"), None)
    if team is None:
        status, team, _ = request(
            "POST",
            "/api/v4/teams",
            {
                "name": "planet-express",
                "display_name": "Planet Express",
                "type": "O",
            },
            token=token,
        )
        team = must(status, team)
    print(f"team {team['name']} {team['id']}")

    def channel(name, display):
        status, found, _ = request(
            "GET",
            f"/api/v4/teams/{team['id']}/channels/name/{name}",
            token=token,
        )
        if status == 200:
            return found
        status, created, _ = request(
            "POST",
            "/api/v4/channels",
            {
                "team_id": team["id"],
                "name": name,
                "display_name": display,
                "type": "O",
            },
            token=token,
        )
        return must(status, created)

    bridge = channel("bridge", "Bridge")
    alerts = channel("alerts", "Alerts")
    print(f"channels bridge={bridge['id']} alerts={alerts['id']}")

    status, hooks, _ = request("GET", "/api/v4/hooks/incoming", token=token)
    hook = None
    if status == 200:
        hook = next((item for item in hooks if item.get("channel_id") == alerts["id"]), None)
    if hook is None:
        status, hook, _ = request(
            "POST",
            "/api/v4/hooks/incoming",
            {
                "channel_id": alerts["id"],
                "display_name": "Lab incoming webhook",
                "description": "TAM interview project",
                "username": "deploy-bot",
            },
            token=token,
        )
        hook = must(status, hook)
    hook_url = f"{BASE}/hooks/{hook['id']}"
    print(f"webhook {hook_url}")
    status, posted, _ = request(
        "POST",
        f"/hooks/{hook['id']}",
        {"text": "Incoming webhook check: Planet Express alerts channel is live."},
    )
    print(f"webhook post HTTP {status}: {posted}")

    for uid in ("fry", "leela", "bender"):
        status, logged, _ = request(
            "POST",
            "/api/v4/users/login",
            {"login_id": uid, "password": uid},
        )
        if status == 200:
            print(f"ldap login {uid} -> {logged['id']} auth={logged.get('auth_service')}")
        else:
            print(f"ldap login {uid} HTTP {status}: {logged}")

    status, sync, _ = request("POST", "/api/v4/ldap/sync", token=token, timeout=120)
    print(f"ldap sync HTTP {status}: {sync if status != 200 else 'started'}")

    groups = None
    status = 0
    for _ in range(20):
        status, groups, _ = request("GET", "/api/v4/ldap/groups?page=0&per_page=100", token=token)
        rows = groups.get("groups", []) if isinstance(groups, dict) else groups
        if not isinstance(rows, list):
            rows = []
        if status == 200 and any(item.get("name") == "ship_crew" for item in rows):
            break
        time.sleep(3)
    else:
        raise SystemExit(f"ship_crew did not appear after LDAP sync (HTTP {status}: {groups})")
    print(f"ldap groups HTTP {status}")
    group_rows = groups.get("groups", groups) if isinstance(groups, dict) else groups
    print(json.dumps(group_rows, indent=2)[:2000])
    ship = next((item for item in group_rows if item.get("name") == "ship_crew"), None)
    if ship is None:
        raise SystemExit("no LDAP groups returned")
    remote = ship.get("primary_key") or ship.get("remote_id") or ship.get("id")
    print(f"linking remote id {remote}")
    status, linked, _ = request("POST", f"/api/v4/ldap/groups/{remote}/link", token=token)
    print(f"link HTTP {status}: {json.dumps(linked)[:500]}")

    status, mattermost_groups, _ = request("GET", "/api/v4/groups?q=ship_crew", token=token)
    print(f"mm groups HTTP {status}: {json.dumps(mattermost_groups)[:800]}")
    group = None
    if isinstance(mattermost_groups, list) and mattermost_groups:
        group = mattermost_groups[0]
    elif isinstance(mattermost_groups, dict) and mattermost_groups.get("groups"):
        group = mattermost_groups["groups"][0]
    if group is None and isinstance(linked, dict) and linked.get("id"):
        group = linked
    if group is None:
        raise SystemExit("linked group id not found")
    gid = group["id"]
    status, patched, _ = request(
        "PUT",
        f"/api/v4/groups/{gid}/patch",
        {"allow_reference": True},
        token=token,
    )
    print(f"patch HTTP {status}: {json.dumps(patched)[:400]}")
    status, team_link, _ = request(
        "POST",
        f"/api/v4/groups/{gid}/teams/{team['id']}/link",
        {"auto_add": True},
        token=token,
    )
    print(f"team link HTTP {status}: {json.dumps(team_link)[:400]}")

    status, sync2, _ = request("POST", "/api/v4/ldap/sync", token=token, timeout=120)
    print(f"second sync HTTP {status}")
    time.sleep(3)
    status, members, _ = request("GET", f"/api/v4/groups/{gid}/members", token=token)
    print(f"members HTTP {status}: {json.dumps(members)[:800]}")

    status, post, _ = request(
        "POST",
        "/api/v4/posts",
        {
            "channel_id": bridge["id"],
            "message": "@ship_crew the bridge is clear. This mention came from LDAP group sync.",
        },
        token=token,
    )
    if status not in (200, 201):
        raise SystemExit(f"mention post HTTP {status}: {post}")
    meta = (post.get("metadata") or {})
    print(f"mention post {post['id']}")
    print("metadata groups", json.dumps(meta.get("groups") or meta.get("embeds") or list(meta.keys())))

    for username in ("fry", "leela", "bender"):
        status, found, _ = request("GET", f"/api/v4/users/username/{username}", token=token)
        if status != 200:
            print(f"skip channel add {username}: HTTP {status}")
            continue
        status, added, _ = request(
            "POST",
            f"/api/v4/channels/{bridge['id']}/members",
            {"user_id": found["id"]},
            token=token,
        )
        print(f"channel member {username} HTTP {status}")

    status, stats, _ = request("GET", "/api/v4/analytics/old?name=extra_counts", token=token)
    rows = must(status, stats)
    session = next((row for row in rows if row.get("name") == "session_count"), None)
    print(f"analytics session_count={session}")

    evidence = {
        "team": team["name"],
        "bridge_channel": bridge["name"],
        "alerts_channel": alerts["name"],
        "webhook_id": hook["id"],
        "group_id": gid,
        "mention_post_id": post["id"],
        "mention_metadata_keys": list(meta.keys()),
        "session_count": None if session is None else session.get("value"),
    }
    out = ROOT / "secrets" / "evidence.json"
    out.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
