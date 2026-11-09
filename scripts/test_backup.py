"""Backup round trip: dump (with paging) -> encrypt -> decrypt -> same data. Run: python scripts/test_backup.py"""
import gzip, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_market as b

rows = {"rates": [{"id": i, "rpm": 2.5} for i in range(b.PAGE + 7)], "polls": [{"id": 1}], "views": [], "visitors": [], "refs": []}
def fake(sql, params):
    t = sql.split("FROM ")[1].split()[0]
    limit, offset = params
    return rows[t][offset:offset + limit]
data = b.dump(fake)
assert len(data["rates"]) == b.PAGE + 7 and "meta" not in data, "paging or table list wrong"
raw = gzip.compress(json.dumps(data).encode())
d = tempfile.mkdtemp(); path = os.path.join(d, "x.enc")
b.encrypt(raw, "a long test passphrase", path)
assert open(path, "rb").read()[:8] == b"Salted__", "not encrypted"
out = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-in", path, "-pass", "pass:a long test passphrase"], capture_output=True, check=True).stdout
assert json.loads(gzip.decompress(out)) == data, "round trip failed"
wrong = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-in", path, "-pass", "pass:wrong"], capture_output=True)
assert wrong.returncode != 0 or wrong.stdout != out, "wrong passphrase must not decrypt"
for k in ("CF_API_TOKEN", "CF_ACCOUNT_ID", "D1_DATABASE_ID", "BACKUP_PASSPHRASE"):
    os.environ.pop(k, None)
assert b.main() == 0, "missing secrets should skip quietly"
print("All backup tests passed.")
