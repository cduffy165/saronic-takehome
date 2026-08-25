"""Turns a plan's app name into a registry slug — shared by Build (the generated
app's directory name) and Register (the App row's slug), so they always agree."""

import re


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "app"
