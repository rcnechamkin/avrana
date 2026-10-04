#!/usr/bin/env python3
"""Read-only checks using recovered configuration; never pin owner passwords."""
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

def config_values(path):
    values = {}
    for line in pathlib.Path(path).read_text().splitlines():
        match = re.match(r"\s*([\w]+)\s*=\s*(.*?)\s*$", line)
        if match and match[1] in {"api_key", "authentication"}:
            values[match[1]] = match[2].strip('"')
    return values

def sab_queue(key):
    query = urllib.parse.urlencode({"mode": "queue", "output": "json", "apikey": key})
    with urllib.request.urlopen("http://10.0.0.218:8082/api?" + query, timeout=10) as response:
        return json.load(response)

def main():
    failed = 0
    try:
        key = config_values("/home/cody/.sabnzbd/sabnzbd.ini").get("api_key")
        if not key:
            raise ValueError("missing key")
        response = sab_queue(key)
        if "queue" not in response:
            raise ValueError("API rejected configured key")
        print("OK   SABnzbd authenticated API access using recovered configuration")
        try:
            bad = sab_queue("recovery-check-invalid-key")
            denied = bool(bad.get("error")) or bad.get("status") is False
        except urllib.error.HTTPError as error:
            denied = error.code in (401, 403)
        if not denied:
            raise ValueError("API accepted invalid key")
        print("OK   SABnzbd rejects invalid API key")
        print("SKIP SABnzbd owner web-password check; no owner password is stored in this checker")
    except Exception as error:
        print("FAIL SABnzbd configured API authentication:", type(error).__name__)
        failed += 1
    try:
        mode = int(config_values("/home/cody/avrana/services/mylar3/config.ini")["authentication"])
        if mode == 0:
            print("WARN Mylar3 authentication is disabled in preserved configuration; recovery has not changed its access policy")
        else:
            print(f"OK   Mylar3 authentication configured (mode {mode}); owner-login confirmation remains separate")
    except Exception as error:
        print("FAIL Mylar3 authentication configuration:", type(error).__name__)
        failed += 1
    return failed

if __name__ == "__main__":
    raise SystemExit(main())
