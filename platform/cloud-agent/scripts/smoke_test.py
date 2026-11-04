#!/usr/bin/env python3
"""End-to-end smoke test against a running cloud-agent instance.

This talks to the real HTTP service.  It intentionally creates and approves one
plan proposal (never an execution).  When the model is unconfigured it asserts
the chat endpoint returns 503; when configured it skips chat to avoid spending
provider tokens unless --allow-chat is supplied.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# Ignore a stale http_proxy/https_proxy on the platform.  The smoke test talks
# to 127.0.0.1 and must not be routed through an unrelated proxy.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class SmokeError(Exception):
    pass


def http_request(base_url, method, path, payload=None, token=None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with OPENER.open(request, timeout=15) as response:
            status = response.status
            response_headers = dict(response.headers)
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        response_headers = dict(exc.headers or {})
        body = exc.read()
    except urllib.error.URLError as exc:
        raise SmokeError("cannot reach %s: %s" % (base_url, exc))
    parsed = None
    if body:
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            parsed = None
    return status, response_headers, body, parsed


def expect(condition, message):
    if not condition:
        raise SmokeError(message)


def expect_status(actual, expected, label):
    allowed = expected if isinstance(expected, (tuple, list)) else (expected,)
    expect(actual in allowed, "%s: expected HTTP %s, got %s" % (label, allowed, actual))


def main(argv=None):
    parser = argparse.ArgumentParser(description="cloud-agent smoke test")
    parser.add_argument("--base-url", default=os.environ.get("CLOUD_AGENT_URL", "http://127.0.0.1:8130"))
    parser.add_argument("--token", default=os.environ.get("CLOUD_AGENT_ACCESS_TOKEN", ""))
    parser.add_argument("--allow-chat", action="store_true", help="also call /api/chat when configured")
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")
    token = args.token

    try:
        status, headers, body, health = http_request(base, "GET", "/api/health")
        expect_status(status, 200, "health")
        expect(isinstance(health, dict), "health response is not JSON")
        expect(health.get("service") == "velaguard-cloud-agent", "health: unexpected service")
        expect((health.get("execution") or {}).get("available") is False, "health: execution must be unavailable")
        print("PASS health service=%s status=%s" % (health.get("service"), health.get("status")))

        status, headers, body, _ = http_request(base, "GET", "/")
        expect_status(status, 200, "static index")
        expect(b"VelaGuard" in body, "static index: missing VelaGuard title")
        csp = " ".join("%s: %s" % (key, value) for key, value in headers.items() if key.lower() == "content-security-policy")
        expect("default-src 'self'" in csp, "static index: missing same-origin CSP")
        print("PASS static index same-origin CSP")

        status, headers, body, routes = http_request(base, "GET", "/api/routes", token=token)
        expect_status(status, 200, "routes")
        route_index = routes.get("routes") if isinstance(routes.get("routes"), list) else []
        route_ids = [item.get("id") for item in route_index if isinstance(item, dict)]
        expect(routes.get("source"), "routes: missing source")
        print("PASS routes count=%d source=%s" % (len(route_ids), routes.get("source")))

        status, headers, body, fleet = http_request(base, "GET", "/api/fleet", token=token)
        expect_status(status, 200, "fleet")
        snapshot = fleet.get("snapshot") or {}
        expect(snapshot.get("is_live") is False, "fleet: snapshot must not claim live telemetry")
        expect(snapshot.get("telemetry") == "not_connected", "fleet: telemetry must be not_connected")
        print("PASS fleet registry_only robots=%d" % len(snapshot.get("robots") or []))

        unknown_mission = {"route_id": "route-z-smoke", "checks": ["aisle_clear"]}
        status, headers, body, result = http_request(
            base, "POST", "/api/missions/validate", unknown_mission, token
        )
        expect_status(status, 422, "validate unknown route")
        expect((result.get("error") or {}).get("code") == "unknown_route", "validate unknown route: wrong error code")
        expect(result.get("clarification_required") is True, "validate unknown route: clarification not required")
        print("PASS unknown route rejected with clarification")

        status, headers, body, before = http_request(base, "GET", "/api/proposals", token=token)
        expect_status(status, 200, "proposals before")
        count_before = before.get("total")

        status, headers, body, result = http_request(
            base, "POST", "/api/proposals", unknown_mission, token
        )
        expect_status(status, 422, "proposal unknown route")
        expect(result.get("proposal_created") is False, "proposal unknown route: must not create a proposal")

        status, headers, body, after = http_request(base, "GET", "/api/proposals", token=token)
        expect_status(status, 200, "proposals after")
        expect(after.get("total") == count_before, "proposal unknown route: store count changed")
        print("PASS unknown route created no proposal")

        proposal_id = None
        enabled_routes = [
            item
            for item in route_index
            if isinstance(item, dict) and item.get("enabled") and item.get("checks")
        ]
        if not enabled_routes:
            # The production registry is intentionally empty until a maintainer
            # completes calibration and registration.  Do not fabricate route-a.
            print("SKIP registry-dependent validation/proposal (no calibrated routes in the production registry)")
        else:
            route = enabled_routes[0]
            route_id = route.get("id")
            check_id = route["checks"][0].get("id")

            invalid_check = {"route_id": route_id, "checks": ["not_a_registered_check"]}
            status, headers, body, result = http_request(
                base, "POST", "/api/missions/validate", invalid_check, token
            )
            expect_status(status, 422, "validate unknown check")
            expect((result.get("error") or {}).get("code") == "unknown_check", "validate unknown check: wrong error code")
            print("PASS unknown check rejected")

            valid_mission = {
                "route_id": route_id,
                "checks": [check_id],
                "rationale": "deployment smoke test; this is a plan, not an execution",
            }
            status, headers, body, validation = http_request(
                base, "POST", "/api/missions/validate", valid_mission, token
            )
            expect_status(status, 200, "validate registered route")
            expect(validation.get("ok") is True, "validate registered route: not ok")
            expect(validation.get("clarification_required") is False, "validate registered route: unexpected clarification")
            print("PASS registered route validation id=%s" % route_id)

            status, headers, body, created = http_request(
                base, "POST", "/api/proposals", valid_mission, token
            )
            expect_status(status, 201, "create proposal")
            expect(created.get("proposal_created") is True, "create proposal: proposal_created is not true")
            proposal = created.get("proposal") or {}
            proposal_id = created.get("proposal_id") or proposal.get("proposal_id")
            expect(proposal_id, "create proposal: missing proposal_id")
            expect(proposal.get("status") == "pending_confirmation", "create proposal: not pending confirmation")
            expect((proposal.get("execution") or {}).get("state") == "not_executed", "create proposal: execution is not not_executed")
            print("PASS proposal created id=%s status=pending_confirmation execution=not_executed" % proposal_id)

            status, headers, body, decision = http_request(
                base,
                "POST",
                "/api/proposals/%s/decision" % proposal_id,
                {"decision": "approve", "actor": "smoke-test", "note": "plan confirmed; no execution expected"},
                token,
            )
            expect_status(status, 200, "approve proposal")
            decided = decision.get("proposal") or {}
            expect(decided.get("status") == "confirmed_not_executed", "approve: status must be confirmed_not_executed")
            expect((decided.get("execution") or {}).get("state") == "not_executed", "approve: execution must stay not_executed")
            expect((decided.get("approval") or {}).get("state") == "approved", "approve: approval state not approved")
            print("PASS approval recorded, still not executed")

            status, headers, body, duplicate = http_request(
                base,
                "POST",
                "/api/proposals/%s/decision" % proposal_id,
                {"decision": "reject"},
                token,
            )
            expect_status(status, 409, "duplicate decision")
            print("PASS duplicate decision rejected")

        configured = bool((health.get("llm") or {}).get("configured"))
        if not configured:
            status, headers, body, chat = http_request(
                base, "POST", "/api/chat", {"message": "smoke test"}, token
            )
            expect_status(status, 503, "chat unconfigured")
            expect((chat.get("error") or {}).get("code") == "llm_not_configured", "chat: wrong error code")
            print("PASS unconfigured chat returns 503 without mock reply")
        elif args.allow_chat:
            status, headers, body, chat = http_request(
                base, "POST", "/api/chat", {"message": "只读取能力，不要创建计划。"}, token
            )
            expect_status(status, 200, "chat configured")
            expect(chat.get("reply"), "chat: empty reply")
            print("PASS configured chat returned a reply")
        else:
            print("SKIP configured chat (use --allow-chat to spend provider tokens)")

        print("SMOKE_OK=1")
        print("SMOKE_PROPOSAL_ID=%s" % (proposal_id or "none"))
        if proposal_id:
            print("NOTE=smoke test leaves one approved test proposal in the store")
        else:
            print("NOTE=production registry is empty; no test proposal was created")
        return 0
    except SmokeError as exc:
        print("SMOKE_FAILED=1", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
