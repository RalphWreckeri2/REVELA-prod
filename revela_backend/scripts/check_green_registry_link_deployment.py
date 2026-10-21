"""Read-only deployment smoke check: OPTIONS and unauthenticated GET only.

Never submits an inspection, sends a JWT, logs in, or queries business data.
Redirects are reported instead of followed, so proxy/routing errors stay visible.
"""
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_response(opener, method, url, headers):
    request = Request(url, method=method, headers=headers)
    try:
        response = opener.open(request, timeout=20)
    except HTTPError as error:
        response = error  # Include the actual failing status, headers and body.
    with response:
        return {
            "method": method, "url": url, "status": response.code,
            "headers": {name.lower(): value for name, value in response.headers.items()},
            "body": response.read(4096).decode("utf-8", errors="replace"),
        }


def check_deployment(api_origin, frontend_origin, report_id=0, business_id="DEPLOYMENT-PROBE", *, opener=None):
    opener = opener or build_opener(NoRedirects())
    base = f"{api_origin.rstrip('/')}/api/inspections/{report_id}"
    review_url = f"{base}/green-registry-link?{urlencode({'businessID': business_id})}"
    checks = []
    # Match api.js: review sends Authorization; verification also sends JSON.
    for url, method, requested_headers in (
        (review_url, "GET", "authorization"),
        (f"{base}/verify", "POST", "authorization,content-type"),
    ):
        response = read_response(opener, "OPTIONS", url, {
            "Origin": frontend_origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": requested_headers,
        })
        headers = response["headers"]
        allowed_headers = {part.strip().lower() for part in headers.get("access-control-allow-headers", "").split(",")}
        allowed_methods = {part.strip().upper() for part in headers.get("access-control-allow-methods", "").split(",")}
        response["passed"] = (
            200 <= response["status"] < 300
            and "location" not in headers
            and headers.get("access-control-allow-origin") == frontend_origin
            and method in allowed_methods
            and set(requested_headers.split(",")).issubset(allowed_headers)
        )
        checks.append(response)
    # A missing endpoint returns 404 even if it has perfectly valid CORS headers.
    # A deployed, protected review endpoint returns 401 before any DB lookup.
    response = read_response(opener, "GET", review_url, {"Origin": frontend_origin})
    response["passed"] = (
        response["status"] == 401
        and response["headers"].get("access-control-allow-origin") == frontend_origin
        and "location" not in response["headers"]
    )
    checks.append(response)
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-origin", default="https://api.revelasys.site")
    parser.add_argument("--frontend-origin", default="https://www.revelasys.site")
    parser.add_argument("--report-id", type=int, default=0)
    parser.add_argument("--business-id", default="DEPLOYMENT-PROBE")
    args = parser.parse_args()
    try:
        result = check_deployment(args.api_origin, args.frontend_origin, args.report_id, args.business_id)
    except (URLError, TimeoutError, OSError) as error:
        print(json.dumps({"passed": False, "network_error": str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
