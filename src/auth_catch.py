"""Catch Spotify's OAuth redirect locally and mint a refresh token.

    python src/auth_catch.py

Runs a throwaway web server on port 8888, prints the consent link, and waits.
Open the link, approve, and the browser lands back here: the code is exchanged,
the refresh token is written into src/.env, and the server shuts down. Nothing
to copy by hand.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import os
import sys
import urllib.parse

from dotenv import load_dotenv
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError

ENV_PATH = Path(__file__).with_name(".env")
SCOPE = "user-read-recently-played"
PORT = 8888

load_dotenv(ENV_PATH)

PAGE = """<!doctype html><meta charset="utf-8"><title>{title}</title>
<body style="font:16px/1.6 system-ui,sans-serif;max-width:34rem;margin:4rem auto;
padding:0 1.5rem;background:#10151b;color:#e8edf2">
<h1 style="font-size:1.4rem;color:{colour}">{title}</h1>
<p>{message}</p>
<p style="color:#93a1af;font-size:.9rem">You can close this tab and return to the terminal.</p>
"""

state = {"done": False, "ok": False}


def require_env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"[auth] {name} is not set in {ENV_PATH}.")
    return value


def write_refresh_token(token):
    """Replace REFRESH_TOKEN in src/.env, leaving every other line untouched."""
    lines, replaced = [], False
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("REFRESH_TOKEN="):
            lines.append(f"REFRESH_TOKEN={token}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append(f"REFRESH_TOKEN={token}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


class CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the terminal readable

    def reply(self, status, title, message, colour):
        body = PAGE.format(title=title, message=message, colour=colour).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if "error" in query:
            reason = query["error"][0]
            self.reply(400, "Spotify returned an error", reason, "#d9705c")
            print(f"DENIED: {reason}", flush=True)
            state["done"] = True
            return

        if "code" not in query:
            self.reply(404, "Waiting for Spotify",
                       "No authorization code on this URL.", "#e0a341")
            return

        # The redirect_uri in the exchange must byte-match the one that produced
        # the code. Echoing the Host header keeps localhost and 127.0.0.1 both
        # working, whichever the app has registered.
        host = self.headers.get("Host", f"localhost:{PORT}")
        redirect_uri = f"http://{host}/callback"

        try:
            oauth = SpotifyOAuth(
                client_id=require_env("CLIENT_ID"),
                client_secret=require_env("CLIENT_SECRET"),
                redirect_uri=redirect_uri,
                scope=SCOPE,
                cache_handler=MemoryCacheHandler(),
            )
            token_info = oauth.get_access_token(query["code"][0], check_cache=False)
        except SpotifyOauthError as error:
            self.reply(400, "Token exchange failed", str(error), "#d9705c")
            print(f"EXCHANGE FAILED (redirect_uri={redirect_uri}): {error}", flush=True)
            state["done"] = True
            return

        token = token_info.get("refresh_token")
        if not token:
            self.reply(400, "No refresh token returned",
                       "Retry with show_dialog=true.", "#d9705c")
            print("NO REFRESH TOKEN RETURNED", flush=True)
            state["done"] = True
            return

        write_refresh_token(token)
        self.reply(200, "Connected",
                   "Refresh token saved. The collector can run unattended again.",
                   "#5baa9c")
        print(f"SUCCESS: refresh token written to {ENV_PATH} "
              f"(length {len(token)}, redirect_uri {redirect_uri})", flush=True)
        state["done"] = True
        state["ok"] = True


def consent_url(redirect_uri):
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": require_env("CLIENT_ID"),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "show_dialog": "true",
    })


def main():
    registered = os.environ.get("REDIRECT_URI", f"http://127.0.0.1:{PORT}/callback")

    print("Open this link, log in as the account you collect, and click Agree:\n")
    print(f"   {consent_url(registered)}\n")
    print(f"Waiting on http://localhost:{PORT}/callback ... (Ctrl+C to stop)\n")

    server = HTTPServer(("0.0.0.0", PORT), CallbackHandler)
    server.timeout = 1
    try:
        while not state["done"]:
            server.handle_request()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 1
    finally:
        server.server_close()

    return 0 if state["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
