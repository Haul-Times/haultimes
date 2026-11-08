"""Shared settings and helpers for the HaulTimes scripts."""

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# HAULTIMES_DATA / HAULTIMES_SITE let you build a test copy without touching the real site.
DATA = os.environ.get("HAULTIMES_DATA") or os.path.join(ROOT, "data")
SITE = os.environ.get("HAULTIMES_SITE") or os.path.join(ROOT, "site")
STATIC = os.path.join(ROOT, "static")
IMAGES = os.path.join(ROOT, "images")

# Topic key -> (menu label, page slug)
CATEGORIES = {
    "rates":   ("Rates & Market", "rates-and-market"),
    "border":  ("Cross-Border", "cross-border"),
    "regs":    ("Regulations", "regulations"),
    "fuel":    ("Fuel", "fuel"),
    "equip":   ("Equipment", "equipment"),
    "drivers": ("Drivers & Jobs", "drivers-and-jobs"),
    "other":   ("Industry", "industry"),
}


def load_config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def load_json(name, default):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(name, data):
    os.makedirs(DATA, exist_ok=True)
    tmp = os.path.join(DATA, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(DATA, name))


def slugify(text, limit=70):
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:limit].rstrip("-") or "story"
