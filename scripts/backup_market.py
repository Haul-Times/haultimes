"""Weekly encrypted backup of the Freight Market reader database (Cloudflare D1).

Reads every table through Cloudflare's D1 API, compresses it and encrypts it with a passphrase
that only you know (GitHub secret BACKUP_PASSPHRASE), then saves it under backups/.
The file is unreadable without the passphrase, so it is safe even in a public repository.

To open a backup on your own computer (Mac or Linux terminal):
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in backups/market-YYYY-MM-DD.json.gz.enc -out market.json.gz
  gunzip market.json.gz          (asks for the passphrase in the first step)
"""

import gzip
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

from common import ROOT

TABLES = ["rates", "polls", "views", "visitors", "refs"]   # 'meta' holds the spam-filter secret, so it is left out
PAGE = 5000


def d1_query(account, database, token, sql, params=()):
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/accounts/%s/d1/database/%s/query" % (account, database),
        data=json.dumps({"sql": sql, "params": list(params)}).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    if not body.get("success"):
        raise RuntimeError("D1 API error: %s" % body.get("errors"))
    return body["result"][0]["results"]


def dump(query):
    out = {}
    for t in TABLES:
        rows, offset = [], 0
        while True:
            try:
                chunk = query("SELECT * FROM %s ORDER BY rowid LIMIT ? OFFSET ?" % t, (PAGE, offset))
            except RuntimeError as e:
                if "no such table" in str(e):
                    chunk = []
                else:
                    raise
            rows += chunk
            if len(chunk) < PAGE:
                break
            offset += PAGE
        out[t] = rows
    return out


def encrypt(raw, passphrase, path):
    env = dict(os.environ, BACKUP_PASSPHRASE=passphrase)
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-salt", "-pass", "env:BACKUP_PASSPHRASE", "-out", path],
                   input=raw, env=env, check=True)


def main():
    need = ["CF_API_TOKEN", "CF_ACCOUNT_ID", "D1_DATABASE_ID", "BACKUP_PASSPHRASE"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        print("Backup skipped: missing GitHub secrets %s" % ", ".join(missing))
        return 0
    if len(os.environ["BACKUP_PASSPHRASE"]) < 12:
        print("Backup skipped: BACKUP_PASSPHRASE must be at least 12 characters.")
        return 1
    q = lambda sql, p=(): d1_query(os.environ["CF_ACCOUNT_ID"], os.environ["D1_DATABASE_ID"], os.environ["CF_API_TOKEN"], sql, p)
    now = datetime.now(timezone.utc)
    data = {"created": now.isoformat(), "tables": dump(q)}
    raw = gzip.compress(json.dumps(data, separators=(",", ":")).encode())
    os.makedirs(os.path.join(ROOT, "backups"), exist_ok=True)
    path = os.path.join(ROOT, "backups", "market-%s.json.gz.enc" % now.strftime("%Y-%m-%d"))
    encrypt(raw, os.environ["BACKUP_PASSPHRASE"], path)
    print("Backup saved: %s (%s)" % (os.path.basename(path), ", ".join("%s %d rows" % (t, len(r)) for t, r in data["tables"].items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
