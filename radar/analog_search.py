from __future__ import annotations

import re
from datetime import datetime, timedelta

from radar.config import RadarConfig
from radar.models import HistoricalSearchQuery, RadarCard


BOILERPLATE_PHRASES = {
    "оказание услуг",
    "выполнение работ",
    "реестровый номер",
    "муниципального района",
    "государственных нужд",
    "нужды заказчика",
}

LOW_VALUE_TOKENS = {
    "оказание",
    "услуг",
    "услуги",
    "выполнение",
    "работ",
    "закупка",
    "создание",
    "разработка",
    "доработка",
    "модернизация",
    "развитие",
    "муниципальный",
    "государственный",
    "обеспечение",
    "нужды",
    "заказчика",
}

TERM_SYNONYMS = {
    "portal": ["портал", "интернет портал", "интернет-портал", "веб портал", "веб-портал", "информационный портал"],
    "website": ["сайт", "веб сайт", "веб-сайт", "интернет сайт", "интернет-сайт"],
    "application": ["заявка", "заявки", "заявок", "обращение", "обращения"],
    "registry": ["реестр", "реестра", "реестров"],
    "account": ["личный кабинет", "кабинет пользователя"],
    "information_system": ["информационная система", "ис", "автоматизированная система"],
    "development": ["разработка", "создание", "доработка", "модернизация", "развитие"],
    "business": ["бизнес", "предпринимательство", "инвестиционный", "инвестиции"],
    "cms": ["cms", "content management"],
    "web_application": ["веб приложение", "веб-приложение", "web application"],
    "admin_panel": ["административная панель", "панель администратора"],
}

TERM_CLASS = {
    "account": "HIGH_VALUE",
    "registry": "MEDIUM_VALUE",
    "portal": "MEDIUM_VALUE",
    "website": "MEDIUM_VALUE",
    "information_system": "MEDIUM_VALUE",
    "business": "HIGH_VALUE",
    "cms": "HIGH_VALUE",
    "web_application": "HIGH_VALUE",
    "admin_panel": "HIGH_VALUE",
    "application": "HIGH_VALUE",
    "development": "LOW_VALUE",
}

TERM_PATTERNS = {
    "account": [r"личн\w+\s+кабинет\w*"],
    "portal": [r"(?:интернет|веб|информационн\w+)?\s*портал\w*"],
    "website": [r"(?:веб|интернет)?\s*сайт\w*"],
    "registry": [r"\bреестр\w*"],
    "information_system": [r"(?:информационн\w+|автоматизированн\w+)\s+систем\w*", r"\bис\b"],
    "web_application": [r"веб\s+приложен\w*", r"web application"],
    "admin_panel": [r"административн\w+\s+панел\w*"],
}


def repair_mojibake(value: str) -> str:
    text = value or ""
    if "Р" not in text and "С" not in text:
        return text
    try:
        repaired = text.encode("cp1251", errors="strict").decode("utf-8", errors="strict")
    except Exception:
        return text
    suspicious_fragments = ("Р°", "Рµ", "Рѕ", "Рї", "С‚", "СЃ", "СЏ", "С‹", "С…", "Р\xa0")
    source_suspicious = sum(text.count(fragment) for fragment in suspicious_fragments)
    repaired_suspicious = sum(repaired.count(fragment) for fragment in suspicious_fragments)
    if source_suspicious > repaired_suspicious:
        return repaired
    return text


def normalize_text(value: str) -> str:
    text = repair_mojibake(value or "").lower().replace("ё", "е")
    text = re.sub(r"[-–—/]+", " ", text)
    text = re.sub(r"[\"'`“”«»(){}\[\]:;,.!?№]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for phrase in sorted(BOILERPLATE_PHRASES, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_token(token: str) -> str:
    normalized = repair_mojibake(token.lower()).replace("ё", "е")
    if normalized.startswith("реестр"):
        return "реестр"
    if normalized.startswith("портал"):
        return "портал"
    if normalized.startswith("сайт"):
        return "сайт"
    if normalized.startswith("заяв"):
        return "заявка"
    if normalized.startswith("обращен"):
        return "обращение"
    return normalized


def normalize_tokens(value: str) -> list[str]:
    text = normalize_text(value)
    raw_tokens = re.findall(r"[a-zа-я0-9]+", text)
    tokens: list[str] = []
    for token in raw_tokens:
        if len(token) <= 2:
            continue
        canonical = canonical_token(token)
        if canonical in LOW_VALUE_TOKENS:
            continue
        tokens.append(canonical)
    return tokens


def canonical_terms_from_text(value: str) -> list[str]:
    normalized = f" {normalize_text(value)} "
    tokens = set(re.findall(r"[a-zа-я0-9]+", normalized))
    matches: list[str] = []
    for canonical, variants in TERM_SYNONYMS.items():
        for variant in variants:
            variant_norm = normalize_text(variant)
            if f" {variant_norm} " in normalized:
                matches.append(canonical)
                break
        else:
            for pattern in TERM_PATTERNS.get(canonical, []):
                if re.search(pattern, normalized):
                    matches.append(canonical)
                    break
            else:
                if canonical == "portal" and any(token.startswith("портал") for token in tokens):
                    matches.append(canonical)
                elif canonical == "website" and any(token.startswith("сайт") for token in tokens):
                    matches.append(canonical)
                elif canonical == "registry" and any(token.startswith("реестр") for token in tokens):
                    matches.append(canonical)
                elif canonical == "web_application" and any(token.startswith("прилож") for token in tokens) and "веб" in tokens:
                    matches.append(canonical)
    return matches


def extract_functional_terms(value: str) -> list[str]:
    return [term for term in canonical_terms_from_text(value) if TERM_CLASS.get(term) != "LOW_VALUE"]


def term_importance(term: str) -> int:
    return {"HIGH_VALUE": 10, "MEDIUM_VALUE": 6, "LOW_VALUE": 1}.get(TERM_CLASS.get(term, "LOW_VALUE"), 1)


def extract_category(value: str) -> str:
    terms = set(canonical_terms_from_text(value))
    if "portal" in terms and "business" in terms:
        return "BUSINESS_PORTAL"
    if "portal" in terms:
        return "PORTAL"
    if "website" in terms:
        return "WEBSITE"
    if "information_system" in terms:
        return "INFORMATION_SYSTEM"
    if "registry" in terms:
        return "REGISTRY_SYSTEM"
    text = normalize_text(value)
    if "1с" in text or "лиценз" in text:
        return "LICENSE_ONLY"
    if any(word in text for word in ["сервер", "оборудован", "компьютер", "поставка"]):
        return "HARDWARE"
    return "OTHER"


def extract_profile(value: str) -> str:
    category = extract_category(value)
    return {
        "BUSINESS_PORTAL": "portal",
        "PORTAL": "portal",
        "WEBSITE": "website",
        "INFORMATION_SYSTEM": "system",
        "REGISTRY_SYSTEM": "system",
        "LICENSE_ONLY": "license",
        "HARDWARE": "hardware",
    }.get(category, "other")


def source_query_candidates(card: RadarCard) -> list[tuple[str, str, int]]:
    normalized_title = normalize_text(card.title)
    terms = extract_functional_terms(f"{card.title} {card.raw_text}")
    queries: list[tuple[str, str, int]] = []

    if "portal" in terms and "business" in terms:
        queries.append(("инвестиционный портал", "SOURCE_EXACT_PHRASE", 4))
        queries.append(("информационный портал", "SOURCE_FUNCTIONAL_TERM", 3))
        queries.append(("портал для бизнеса", "SOURCE_CATEGORY", 3))
    elif "portal" in terms:
        if "интернет портал" in normalized_title:
            queries.append(("интернет портал", "SOURCE_EXACT_PHRASE", 4))
        queries.append(("информационный портал", "SOURCE_FUNCTIONAL_TERM", 3))
        queries.append(("портал", "SOURCE_CATEGORY", 2))
    elif "website" in terms:
        queries.append(("веб сайт", "SOURCE_CATEGORY", 3))
        queries.append(("сайт", "SOURCE_CATEGORY", 2))

    high_value_terms = [term for term in terms if TERM_CLASS.get(term) == "HIGH_VALUE" and term != "development"]
    for term in high_value_terms:
        query_text = {
            "account": "личный кабинет",
            "application": "обработка заявок",
            "cms": "cms",
            "business": "бизнес",
            "web_application": "веб приложение",
            "admin_panel": "административная панель",
        }.get(term)
        if query_text:
            queries.append((query_text, "SOURCE_FUNCTIONAL_TERM", 3))

    if card.customer and extract_category(card.title) in {"BUSINESS_PORTAL", "PORTAL", "WEBSITE", "INFORMATION_SYSTEM"}:
        queries.append((f"{card.customer} портал", "CUSTOMER_CATEGORY", 2))
    return queries


def generate_historical_queries(
    card: RadarCard,
    config: RadarConfig,
    *,
    profile: str = "",
    as_of: datetime | None = None,
) -> list[HistoricalSearchQuery]:
    now = as_of or datetime.now().astimezone()
    date_from = (now - timedelta(days=config.historical.search.lookback_days)).strftime("%d.%m.%Y")
    date_to = now.strftime("%d.%m.%Y")
    queries: list[HistoricalSearchQuery] = []
    seen: set[str] = set()

    def add(text: str, query_type: str, reason: str, weight: int) -> None:
        text = normalize_text(text)
        if not text or text in seen:
            return
        seen.add(text)
        queries.append(
            HistoricalSearchQuery(
                source_procurement_number=card.procurement_number,
                query_text=text,
                query_type=query_type,
                generation_reason=reason,
                law=card.law,
                customer=card.customer,
                region=card.region,
                date_from=date_from,
                date_to=date_to,
                completed_only=True,
                profile=profile,
                weight=weight,
            )
        )

    for text, reason, weight in source_query_candidates(card):
        add(text, "SOURCE_AWARE", reason, weight)

    if not queries:
        terms = extract_functional_terms(f"{card.title} {card.raw_text}")
        for term in terms:
            text = {
                "portal": "портал",
                "website": "сайт",
                "information_system": "информационная система",
                "registry": "реестр",
            }.get(term)
            if text:
                add(text, "SOURCE_AWARE", "PROFILE_FALLBACK", 2)

    return queries[: config.historical.search.maximum_queries_per_procurement]


def completed_only_params() -> dict[str, str]:
    return {"pc": "on"}
