#!/usr/bin/env python3
"""Find and rank Moscow beauty leads from public OpenStreetMap data."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


MOSCOW_BBOX = "55.489,37.205,56.009,37.967"
DEFAULT_OVERPASS_URLS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
)

SOCIAL_HOSTS = {
    "instagram.com",
    "t.me",
    "telegram.me",
    "vk.com",
    "vkontakte.ru",
    "youtube.com",
    "tiktok.com",
    "facebook.com",
    "ok.ru",
}
BOOKING_HOSTS = {
    "yclients.com",
    "yclients.ru",
    "dikidi.net",
    "dikidi.ru",
    "bumpix.net",
    "bumpix.com",
    "profi.ru",
}
LINK_PAGE_HOSTS = {
    "taplink.cc",
    "mssg.me",
    "linktr.ee",
    "hipolink.me",
    "meconnect.ru",
    "salon.link",
}

URL_TAGS = (
    "contact:website",
    "website",
    "contact:instagram",
    "instagram",
    "contact:telegram",
    "telegram",
    "contact:vk",
    "vk",
    "contact:facebook",
    "facebook",
)

PHONE_TAGS = ("contact:phone", "phone", "contact:mobile", "mobile")

CATEGORY_NAMES = {
    "hairdresser": "волосами",
    "hair": "волосами",
    "nails": "маникюром",
    "manicure": "маникюром",
    "pedicure": "педикюром",
    "eyebrows": "бровями",
    "lashes": "ресницами",
    "skincare": "уходом за кожей",
    "cosmetics": "косметологией",
    "massage": "массажем",
    "spa": "SPA-услугами",
    "tanning": "загаром",
    "waxing": "депиляцией",
}


@dataclass
class Lead:
    source_id: str
    name: str
    category: str
    address: str
    phone: str
    website_url: str
    booking_url: str
    social_url: str
    source_url: str
    score: int = 0
    priority: str = ""
    reasons: list[str] = field(default_factory=list)
    message: str = ""


def hostname(value: str) -> str:
    if not value:
        return ""
    candidate = value.strip()
    if candidate.startswith("@"):
        return ""
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        host = (urlparse(candidate).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


def host_matches(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def normalize_url(value: str, kind: str = "") -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("@"):
        handle = value[1:]
        if "telegram" in kind:
            return f"https://t.me/{handle}"
        if "instagram" in kind:
            return f"https://instagram.com/{handle}"
        if "vk" in kind:
            return f"https://vk.com/{handle}"
    if value.startswith("//"):
        return "https:" + value
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.I):
        return "https://" + value.lstrip("/")
    return value


def address_from_tags(tags: dict[str, str]) -> str:
    full = tags.get("addr:full", "").strip()
    if full:
        return full
    parts = [
        tags.get("addr:street", "").strip(),
        tags.get("addr:housenumber", "").strip(),
    ]
    return ", ".join(part for part in parts if part)


def category_from_tags(tags: dict[str, str]) -> str:
    raw = ";".join(
        filter(
            None,
            (
                tags.get("beauty", ""),
                tags.get("shop", ""),
                tags.get("craft", ""),
                tags.get("service", ""),
            ),
        )
    ).lower()
    for key, label in CATEGORY_NAMES.items():
        if key in raw:
            return label
    return "бьюти-услугами"


def split_links(tags: dict[str, str]) -> tuple[str, str, str]:
    standalone = ""
    booking = ""
    social = ""
    for key in URL_TAGS:
        value = normalize_url(tags.get(key, ""), key)
        host = hostname(value)
        if not value or not host:
            continue
        if host_matches(host, BOOKING_HOSTS):
            booking = booking or value
        elif host_matches(host, SOCIAL_HOSTS) or host_matches(host, LINK_PAGE_HOSTS):
            social = social or value
        else:
            standalone = standalone or value
    return standalone, booking, social


def phone_from_tags(tags: dict[str, str]) -> str:
    for key in PHONE_TAGS:
        if tags.get(key, "").strip():
            return tags[key].strip()
    return ""


def score_lead(lead: Lead) -> Lead:
    score = 0
    reasons: list[str] = []
    if not lead.website_url:
        score += 35
        reasons.append("нет полноценного сайта")
    else:
        score -= 25
        reasons.append("уже есть отдельный сайт")
    if lead.booking_url:
        score += 28
        reasons.append("есть онлайн-запись")
    if lead.social_url:
        score += 15
        reasons.append("есть соцсеть или страница-ссылка")
    if lead.phone:
        score += 10
        reasons.append("есть контактный телефон")
    if lead.address:
        score += 5
        reasons.append("указан адрес")
    if lead.category != "бьюти-услугами":
        score += 7
        reasons.append("понятна специализация")

    lead.score = max(0, min(100, score))
    lead.priority = "A" if lead.score >= 70 else "B" if lead.score >= 50 else "C"
    lead.reasons = reasons
    return lead


def make_message(lead: Lead) -> str:
    name = lead.name.strip() or "вашу страницу"
    if lead.booking_url:
        opening = (
            f"Добрый день! Увидел {name}: у вас уже есть онлайн-запись, "
            "но перед ней новому клиенту приходится отдельно искать примеры работ, "
            "стоимость и понимать, какой результат он получит."
        )
    else:
        opening = (
            f"Добрый день! Увидел {name} и то, что вы занимаетесь {lead.category}. "
            "Новому клиенту перед записью важно сразу увидеть примеры работ, цены "
            "и понять, какой результат он получит."
        )
    return (
        opening
        + "\n\nМогу сделать для вас компактный сайт с работами, ценами, описанием услуг "
        "и удобной записью. Его также можно подготовить к поиску в Яндексе по вашим услугам в Москве."
        + "\n\nЕсли интересно, бесплатно подготовлю небольшой пример под вас. Показать?"
    )


def element_to_lead(element: dict) -> Lead | None:
    tags = element.get("tags") or {}
    name = tags.get("name", "").strip()
    if not name:
        return None
    website, booking, social = split_links(tags)
    element_type = str(element.get("type", "node"))
    element_id = str(element.get("id", ""))
    lead = Lead(
        source_id=f"{element_type}/{element_id}",
        name=name,
        category=category_from_tags(tags),
        address=address_from_tags(tags),
        phone=phone_from_tags(tags),
        website_url=website,
        booking_url=booking,
        social_url=social,
        source_url=f"https://www.openstreetmap.org/{element_type}/{element_id}",
    )
    score_lead(lead)
    lead.message = make_message(lead)
    return lead


def deduplicate(leads: Iterable[Lead]) -> list[Lead]:
    result: dict[str, Lead] = {}
    for lead in leads:
        phone_key = re.sub(r"\D", "", lead.phone)
        key = phone_key or re.sub(r"\W", "", lead.name.lower(), flags=re.UNICODE)
        previous = result.get(key)
        if previous is None or lead.score > previous.score:
            result[key] = lead
    return sorted(result.values(), key=lambda item: (-item.score, item.name.lower()))


def overpass_query(bbox: str) -> str:
    return f"""[out:json][timeout:25];
(
  nwr[\"shop\"~\"^(hairdresser|beauty)$\"][\"name\"]({bbox});
  nwr[\"beauty\"][\"name\"]({bbox});
  nwr[\"craft\"=\"beautician\"][\"name\"]({bbox});
);
out tags;"""


def fetch_overpass(bbox: str, endpoints: Iterable[str] = DEFAULT_OVERPASS_URLS) -> dict:
    data = urllib.parse.urlencode({"data": overpass_query(bbox)}).encode("utf-8")
    errors: list[str] = []
    for endpoint in endpoints:
        print(f"Пробую источник: {endpoint}", file=sys.stderr, flush=True)
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "User-Agent": "BeautyLeadFinder/1.0 (public business research)",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            errors.append(f"{endpoint}: {exc}")
            time.sleep(0.5)
    raise RuntimeError("Не удалось получить данные из Overpass:\n" + "\n".join(errors))


def load_payload(path: Path | None, bbox: str) -> dict:
    if path:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    custom = os.environ.get("OVERPASS_URL", "").strip()
    endpoints = (custom,) if custom else DEFAULT_OVERPASS_URLS
    return fetch_overpass(bbox, endpoints)


def leads_from_payload(payload: dict, minimum_score: int) -> list[Lead]:
    leads = (element_to_lead(element) for element in payload.get("elements", []))
    return [lead for lead in deduplicate(item for item in leads if item) if lead.score >= minimum_score]


def write_csv(leads: list[Lead], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "priority",
        "score",
        "name",
        "category",
        "address",
        "phone",
        "social_url",
        "booking_url",
        "website_url",
        "source_url",
        "reasons",
        "message",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for lead in leads:
            row = asdict(lead)
            row["reasons"] = "; ".join(lead.reasons)
            writer.writerow({field: row[field] for field in fields})


def link(value: str, label: str) -> str:
    if not value:
        return ""
    return f'<a href="{html.escape(value, quote=True)}" target="_blank" rel="noreferrer">{label}</a>'


def write_html(leads: list[Lead], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = {priority: sum(item.priority == priority for item in leads) for priority in "ABC"}
    cards: list[str] = []
    for index, lead in enumerate(leads, start=1):
        links = " ".join(
            filter(
                None,
                (
                    link(lead.social_url, "Соцсеть"),
                    link(lead.booking_url, "Запись"),
                    link(lead.website_url, "Сайт"),
                    link(lead.source_url, "Источник"),
                ),
            )
        )
        reasons = "".join(f"<li>{html.escape(reason)}</li>" for reason in lead.reasons)
        cards.append(
            f"""
            <article class="lead" data-priority="{lead.priority}">
              <header><span class="badge p{lead.priority}">{lead.priority}</span><strong>{lead.score}</strong><h2>{html.escape(lead.name)}</h2></header>
              <p class="meta">{html.escape(lead.category)} · {html.escape(lead.address or 'Москва')}</p>
              <nav>{links}</nav>
              <ul>{reasons}</ul>
              <div class="message"><button type="button" data-copy="message-{index}">Скопировать сообщение</button><pre id="message-{index}">{html.escape(lead.message)}</pre></div>
            </article>"""
        )

    document = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Beauty Lead Finder — Москва</title>
<style>
:root{{--bg:#f2efe8;--card:#fff;--ink:#171815;--muted:#6d7169;--lime:#c9ff2e;--orange:#ff6330;--line:#d9d6ce}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Arial,sans-serif}}
main{{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:56px 0}}h1{{margin:0;font-size:clamp(40px,7vw,84px);line-height:.9;letter-spacing:-.065em}}
.summary{{margin:35px 0 28px;display:flex;gap:12px;flex-wrap:wrap}}.summary span{{padding:10px 14px;border:1px solid var(--line);background:#faf8f3;font-weight:700}}
.filters{{margin-bottom:24px;display:flex;gap:8px}}button{{border:0;padding:11px 14px;background:var(--ink);color:#fff;font-weight:700;cursor:pointer}}.filters button.active{{background:var(--lime);color:var(--ink)}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}}.lead{{padding:24px;background:var(--card);border:1px solid var(--line)}}
.lead header{{display:grid;grid-template-columns:38px 38px 1fr;align-items:center;gap:8px}}.lead h2{{margin:0;font-size:21px}}.badge{{width:32px;height:32px;display:grid;place-items:center;border-radius:50%;font-weight:900}}.pA{{background:var(--lime)}}.pB{{background:#ffd45c}}.pC{{background:#ddd}}
.meta{{color:var(--muted)}}nav{{display:flex;gap:12px;flex-wrap:wrap}}a{{color:var(--ink);font-weight:700}}ul{{padding-left:20px;color:var(--muted)}}.message{{margin-top:18px;border-top:1px solid var(--line);padding-top:16px}}pre{{white-space:pre-wrap;font:13px/1.5 Arial,sans-serif;color:#343631}}
footer{{margin-top:28px;color:var(--muted);font-size:12px}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}main{{padding-top:32px}}}}
</style></head><body><main>
<h1>Beauty Lead Finder</h1><p>Бьюти-мастера и салоны Москвы без полноценного сайта.</p>
<div class="summary"><span>Всего: {len(leads)}</span><span>A: {counts['A']}</span><span>B: {counts['B']}</span><span>C: {counts['C']}</span></div>
<div class="filters"><button class="active" data-filter="all">Все</button><button data-filter="A">Приоритет A</button><button data-filter="B">Приоритет B</button></div>
<section class="grid">{''.join(cards) or '<p>Подходящие лиды не найдены.</p>'}</section>
<footer>Источник данных: OpenStreetMap contributors. Перед отправкой сообщения проверь актуальность контакта и страницы.</footer>
</main><script>
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.lead').forEach(c=>c.hidden=b.dataset.filter!=='all'&&c.dataset.priority!==b.dataset.filter)}});
document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{{await navigator.clipboard.writeText(document.getElementById(b.dataset.copy).textContent);const old=b.textContent;b.textContent='Скопировано';setTimeout(()=>b.textContent=old,1200)}});
</script></body></html>"""
    path.write_text(document, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Поиск бьюти-лидов Москвы без полноценного сайта")
    parser.add_argument("--input", type=Path, help="Локальный JSON Overpass для повторного анализа")
    parser.add_argument("--bbox", default=MOSCOW_BBOX, help="Границы south,west,north,east")
    parser.add_argument("--min-score", type=int, default=50, help="Минимальный балл лида")
    parser.add_argument("--limit", type=int, default=100, help="Максимум лидов в отчёте")
    parser.add_argument("--output-dir", type=Path, default=Path("lead-output"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = load_payload(args.input, args.bbox)
        leads = leads_from_payload(payload, args.min_score)[: max(0, args.limit)]
        write_csv(leads, args.output_dir / "leads.csv")
        write_html(leads, args.output_dir / "leads.html")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"Готово: {len(leads)} лидов")
    print(f"CSV: {(args.output_dir / 'leads.csv').resolve()}")
    print(f"Отчёт: {(args.output_dir / 'leads.html').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
