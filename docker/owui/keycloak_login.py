"""Signs a Keycloak user in to the Open WebUI test instance, as a browser would, and prints its Open WebUI token.

    python3 docker/owui/keycloak_login.py julie muffin-dev

The first sign-in creates the user in Open WebUI, with their Keycloak subject in `oauth.oidc.sub` (#453).
"""

import html
import re
import sys
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar, DefaultCookiePolicy

OWUI = "http://localhost:3001"


def main(username: str, password: str) -> None:
    # Keycloak's login cookies are Secure, which a browser accepts on localhost over http and this module does not.
    jar = CookieJar(DefaultCookiePolicy(secure_protocols=("https", "wss", "http")))
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    login_page = opener.open(f"{OWUI}/oauth/oidc/login").read().decode()
    action = re.search(r'<form[^>]*action="([^"]+)"', login_page)
    if action is None:
        sys.exit(
            "no Keycloak login form: is the open-webui client imported (docker/keycloak/realm-muffin.json)?"
        )
    data = urllib.parse.urlencode(
        {"username": username, "password": password, "credentialId": ""}
    ).encode()
    opener.open(html.unescape(action.group(1)), data)
    token = next((cookie.value for cookie in jar if cookie.name == "token"), None)
    if token is None:
        sys.exit("signed in to Keycloak, but Open WebUI set no token")
    print(token)


if __name__ == "__main__":
    main(*sys.argv[1:3])
