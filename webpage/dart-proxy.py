#!/usr/bin/env python3
"""
Local proxy for the DART REST API, for use with ALANIS.

This version AUTO-DETECTS how DART wants the API key: on the first request it
tries several common auth styles until one gets a non-4xx answer, then keeps
using the winner. Watch the terminal — it prints which style worked.

Run:  py dart_proxy.py     (leave it running)
Test: http://localhost:8010/posl?ctl=1&age=1200&g=3

Keep this file private — it contains the API key.
"""

import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------- configuration ----------------
DART_BASE = "https://dart.wabtec.com/dart/csx/rest"
API_KEY = "YOUR_DART_API_KEY_HERE"  # set this before running — do not commit the real key
print(API_KEY[:10])
print(API_KEY[-10:])
print(len(API_KEY))
PORT = 8010

# Auth styles to try, in order. (name, headers, query-param-or-None)
AUTH_STYLES = [
    ("header X-API-Key",            {"X-API-Key": API_KEY},                      None),
    ("header Authorization Bearer", {"Authorization": "Bearer " + API_KEY},      None),
    ("header Authorization raw",    {"Authorization": API_KEY},                  None),
    ("header apikey",               {"apikey": API_KEY},                         None),
    ("query key=",                  {},                                          "key"),
    ("query apikey=",               {},                                          "apikey"),
    ("query api_key=",              {},                                          "api_key"),
    ("query token=",                {},                                          "token"),
    ("no auth at all",              {},                                          None),
]

BASE_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ALANIS/1.0",
}
# -----------------------------------------------

working_style = None  # remembered after first success


def attempt(url, style):
    """Try one auth style. Returns (status, ctype, body)."""
    name, headers, qparam = style
    full_url = url
    if qparam:
        sep = "&" if "?" in url else "?"
        full_url = f"{url}{sep}{qparam}={API_KEY}"
    req = urllib.request.Request(
        full_url, headers={**BASE_HEADERS, **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.headers.get("Content-Type", "application/json"), r.read()
    except urllib.error.HTTPError as e:
        body = e.read()

        print("\nERROR")
        print("Status:", e.code)
        print(body.decode("utf-8", errors="ignore"))
        print(full_url)
        

        return e.code, e.headers.get(
            "Content-Type",
            "application/json"
        ), body
    except Exception as e:
        return None, "application/json", json.dumps(
            {"proxy_error": str(e), "url": full_url}).encode()


class DartProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global working_style
        url = DART_BASE + self.path

        styles = [working_style] if working_style else AUTH_STYLES
        status, ctype, body = None, "application/json", b"{}"

        for style in styles:
            status, ctype, body = attempt(url, style)
            label = style[0]
            print(f"[dart_proxy] {label!r} -> {status}")
            if status is not None and status < 400:
                if working_style is None:
                    working_style = style
                    print(f"[dart_proxy] *** SUCCESS with {label!r} — "
                          f"using this from now on ***")
                break

        if status is None:
            status = 502

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[dart_proxy] {self.address_string()} {format % args}")


if __name__ == "__main__":
    
    print("API Key length:", len(API_KEY))
    print("First 10 chars:", API_KEY[:10])
    print("Last 10 chars:", API_KEY[-10:])


    print(f"DART proxy running at http://localhost:{PORT}")
    print(f"Forwarding to {DART_BASE}")
    print(f"Example: http://localhost:{PORT}/posl?ctl=1&age=1200&g=3")
    print("Press Ctrl+C to stop.")
    HTTPServer(("127.0.0.1", PORT), DartProxyHandler).serve_forever()


