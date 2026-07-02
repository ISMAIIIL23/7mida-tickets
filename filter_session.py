"""
filter_session.py

Fetches cinema sessions (listed in sessions.json) from the MK2 API,
filters each down to the essentials, beautifies it as monospace text,
keeps a local JSON "db" (sessions_db.json, via db.py) updated with the
latest seat availability, and posts the result to a Discord webhook.

Designed to run as a single pass per invocation — scheduling (e.g.
hourly checks) is handled externally, e.g. by a GitHub Actions cron
workflow, rather than an internal sleep loop.
"""

import requests
import json
import sys
import os
from datetime import datetime

from db import load_db, update_session, DB_PATH

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    # 'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Referer': 'https://www.mk2.com/',
    'X-Api-Version': '2.0',
    'sentry-trace': '950508e094224aa5a4c775d365e96a64-9b3cc8e16e7194fb-1',
    'baggage': 'sentry-environment=production,sentry-release=1.75.10-05d3e722,sentry-public_key=8bd065da562db6d5b4ae6187e5386b26,sentry-trace_id=950508e094224aa5a4c775d365e96a64,sentry-org_id=4511116178948096,sentry-transaction=%2Fpanier%2Fseance%2F%3Astep,sentry-sampled=true,sentry-sample_rand=0.5498568540565594,sentry-sample_rate=1',
    'Origin': 'https://www.mk2.com',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'DNT': '1',
    'Sec-GPC': '1',
    'Priority': 'u=4',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache',
    # Requests doesn't support trailers
    # 'TE': 'trailers',
}

BASE_URL = 'https://prod-paris-cf.api.mk2.com/sessions'

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/XXX/YYY")


def send_to_discord(text: str, webhook_url: str = WEBHOOK_URL) -> None:
    """Send a message to a Discord channel via webhook, wrapped in a monospace code block."""
    content = f"```\n{text}\n```"
    # Discord message content is capped at 2000 characters
    if len(content) > 2000:
        content = content[:1990] + "\n...\n```"
    data = {"content": content}
    try:
        resp = requests.post(webhook_url, json=data)
        if resp.status_code >= 300:
            print(f"[warn] Discord webhook returned {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        print(f"[warn] Failed to send Discord webhook: {e}")


def fetch_session(cinema_id: str, session_id: str) -> dict:
    """Fetch a live session from the MK2 API and return the raw JSON."""
    url = f"{BASE_URL}/{cinema_id}/{session_id}"
    response = requests.get(url, headers=headers)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] GET {url} -> {response.status_code}")
    response.raise_for_status()
    return response.json()


def filter_session(data: dict) -> dict:
    film = data.get("film", {})
    cinema = data.get("cinema", {})

    tickets = data.get("tickets", [])
    prices = [t["priceInCents"] for t in tickets if "priceInCents" in t]
    min_price = min(prices) / 100 if prices else None
    max_price = max(prices) / 100 if prices else None

    attributes = [a.get("shortName") for a in data.get("attributes", []) if a.get("shortName")]

    return {
        "session_id": data.get("id"),
        "show_time": data.get("showTime"),
        "is_sold_out": data.get("isSoldOut"),
        "seats_available": data.get("seatsAvailable"),
        "attributes": attributes,

        "film": {
            "id": film.get("id"),
            "title": film.get("title"),
            "runtime_min": film.get("runTime"),
            "synopsis": film.get("synopsis"),
            "rating": film.get("rating", {}).get("name"),
            "genres": [g.get("name") for g in film.get("genres", [])],
            "director": next(
                (p["displayName"] for p in film.get("cast", []) if p.get("personType") == "Director"),
                None,
            ),
            "poster_url": film.get("graphicUrl"),
            "trailer_url": film.get("trailerUrl"),
        },

        "cinema": {
            "id": cinema.get("id"),
            "name": cinema.get("name"),
            "address": f"{cinema.get('address1', '')}, {cinema.get('address2', '')}, {cinema.get('city', '')}".strip(", "),
            "latitude": cinema.get("latitude"),
            "longitude": cinema.get("longitude"),
        },

        "prices_eur": {
            "min": min_price,
            "max": max_price,
            "detail": {t["name"]: t["priceInCents"] / 100 for t in tickets},
        },
    }


def _fmt_time(iso_str: str) -> str:
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        return dt.strftime("%a %d %b %Y - %H:%M")
    except ValueError:
        return iso_str


def _seat_status(seats: int, sold_out: bool) -> str:
    if sold_out or seats == 0:
        return "SOLD OUT"
    if seats <= 10:
        return f"Only {seats} seats left!"
    return f"{seats} seats available"


def beautify(session: dict, index: int = None) -> str:
    """Turn one filtered session dict into a Telegram-monospace text block."""
    film = session["film"]
    cinema = session["cinema"]
    prices = session["prices_eur"]

    header = f"[{film['title']}]"
    if index is not None:
        header = f"[{index}] {header}"

    lines = [
        header,
        f"Time: {_fmt_time(session['show_time'])}",
        f"Cinema: {cinema['name']} - {cinema['address']}",
        f"Tags: {' | '.join(session['attributes'])} | Runtime: {film['runtime_min']} min",
        f"Rating: {film['rating']}" if film.get("rating") else None,
        f"Genres: {', '.join(film['genres'])}" if film.get("genres") else None,
        f"Director: {film['director']}" if film.get("director") else None,
        "",
        f"Seats: {_seat_status(session['seats_available'], session['is_sold_out'])}",
        f"Price: from {prices['min']:.2f} EUR (up to {prices['max']:.2f} EUR)" if prices.get("min") else None,
        "",
        f"Synopsis: {film['synopsis']}" if film.get("synopsis") else None,
        f"Trailer: {film['trailer_url']}" if film.get("trailer_url") else None,
    ]

    return "\n".join(line for line in lines if line is not None)


def beautify_all(sessions: list) -> str:
    """Beautify a list of sessions, each indexed, joined with separators."""
    blocks = [beautify(s, index=i) for i, s in enumerate(sessions)]
    sep = "\n\n" + ("-" * 30) + "\n\n"
    return sep.join(blocks)


def check_once(cinema_id: str, session_id: str) -> None:
    """Fetch a session, filter it, print it, update the db, and notify Discord."""
    raw = fetch_session(cinema_id, session_id)
    filtered = filter_session(raw)

    text = beautify(filtered)
    print(text)

    db = load_db()
    change = update_session(db, filtered)

    if change["changed"]:
        diff = change["seats_after"] - change["seats_before"]
        direction = "freed up" if diff > 0 else "were booked"
        change_line = (f">> Seats changed: {change['seats_before']} -> {change['seats_after']} "
                        f"({abs(diff)} seat(s) {direction})")
    else:
        change_line = ">> No change in seat count since last check."

    print(change_line)
    print(f">> DB updated: {DB_PATH}\n")

    send_to_discord(text + "\n\n" + change_line)


def load_sessions_config(path: str = "sessions.json") -> list:
    """Load the list of {cinema_id, session_id} to watch from a JSON config file."""
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("sessions", [])


def check_all_once(sessions_to_watch: list) -> None:
    """Run a single check pass over every session in the config."""
    for entry in sessions_to_watch:
        try:
            check_once(entry["cinema_id"], entry["session_id"])
        except requests.RequestException as e:
            print(f"[error] Request failed for {entry}: {e}")
        except Exception as e:
            print(f"[error] Unexpected error for {entry}: {e}")


def main():
    """
    Single check pass over every session in sessions.json.
    Scheduling (e.g. hourly) is handled externally by GitHub Actions cron,
    not by an internal loop.
    """
    sessions_to_watch = load_sessions_config()

    if not sessions_to_watch:
        print("No sessions configured in sessions.json.")
        sys.exit(1)

    check_all_once(sessions_to_watch)


if __name__ == "__main__":
    main()
