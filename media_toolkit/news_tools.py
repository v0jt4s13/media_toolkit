"""Utility functions reused across Media Toolkit content workflows."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

try:
    from google.cloud import texttospeech
except ImportError:  # pragma: no cover
    texttospeech = None

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VID_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

DEFAULT_MODEL_VERSION = os.getenv("DEFAULT_MODEL_VERSION", "gpt-4.1-mini")

PROMPTS = [
    {
        "id": "test_summary20_pl",
        "label": "Streszczenie TEST PL (max 20 słów)",
        "system": "Jesteś asystentem, który tworzy zwięzłe zajawki do przeczytania artykułu na portalu londynek.net. Zajawka ma być w języku w jakim dostarczone zostały dane.",
        "user_prefix": "Napisz zajawkę do artykułu w ~20 słowach.\n\nDANE:"
    },
    {
        "id": "test_summary50_pl",
        "label": "Streszczenie TEST PL (max 50 słów)",
        "system": "Jesteś asystentem, który tworzy zwięzłe zajawki do przeczytania artykułu na portalu londynek.net. Zajawka ma być w języku w jakim dostarczone zostały dane.",
        "user_prefix": "Napisz zajawkę do artykułu w ~50 słowach.\n\nDANE:"
    },
    {
        "id": "summary_pl",
        "label": "Streszczenie PL (ok. 120 słów)",
        "system": "Jesteś asystentem, który tworzy zwięzłe streszczenia wiadomości po polsku.",
        "user_prefix": "Streść poniższy artykuł w ~120 słowach. Zachowaj neutralny ton dziennikarski.\n\nDANE:"
    },
    {
        "id": "funny_summary_pl",
        "label": "Humorystyczne streszczenie PL (ok. 120 słów)",
        "system": "Jesteś asystentem z dużym poczuciem humoru, zajmujesz się tworzeniem streszczeń wiadomości po polsku.",
        "user_prefix": "Streść poniższy artykuł w ~120 słowach.\n\nDANE:"
    },
    {
        "id": "radio_tone_pl",
        "label": "Przepisz w tonie radiowym (PL)",
        "system": "Jesteś lektorem-redaktorem. Uprość konstrukcje zdań, zachowaj sens.",
        "user_prefix": "Przepisz tekst w tonie radiowym do odczytu na antenie. Krótsze zdania, klarowna składnia.\n\nDANE:"
    },
    {
        "id": "titles5_pl",
        "label": "5 tytułów (PL)",
        "system": "Jesteś redaktorem tytułów prasowych.",
        "user_prefix": "Zaproponuj 5 zwięzłych, nieclickbaitowych tytułów na podstawie danych.\n\nDANE:"
    },
]


def get_prompt_by_id(pid: str) -> Optional[Dict[str, str]]:
    for prompt in PROMPTS:
        if prompt["id"] == pid:
            return prompt
    return None


def detect_media_type(path_or_url: str) -> Optional[str]:
    if not path_or_url:
        return None
    s = path_or_url.strip()

    if s.startswith("data:"):
        header = s[5:].split(";", 1)[0].lower()
        if header.startswith("image/"):
            return "image"
        if header.startswith("video/"):
            return "video"

    try:
        parts = urlsplit(s)
        path = parts.path or s
        query = parts.query or ""
    except Exception:
        path, query = s, ""

    path = path.split("?", 1)[0].split("#", 1)[0]
    suffixes = [ext.lower() for ext in PurePosixPath(path).suffixes]
    for ext in reversed(suffixes):
        if ext in IMG_EXT:
            return "image"
        if ext in VID_EXT:
            return "video"

    if query:
        params = dict(parse_qsl(query.lower(), keep_blank_values=True))
        fmt = params.get("format") or params.get("ext")
        if fmt:
            fmt = fmt.strip(".").lower()
            if f".{fmt}" in IMG_EXT:
                return "image"
            if f".{fmt}" in VID_EXT:
                return "video"

    lower_path = path.lower()
    if any(ext in lower_path for ext in IMG_EXT):
        return "image"
    if any(ext in lower_path for ext in VID_EXT):
        return "video"
    return None


def absolutize(url: str, base: str) -> str:
    try:
        return urljoin(base, url)
    except Exception:
        return url


def fetch_html(page_url: str, timeout: int = 15) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MediaToolkitBot/1.0; +https://example.local)"
    }
    response = requests.get(page_url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def extract_article(html: str, base_url: str) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip() or title

    candidates = []
    for selector in ("article", "[role=main]", "#content", ".content", ".article", ".post", ".entry-content", ".news", ".story"):
        node = soup.select_one(selector)
        if node:
            candidates.append(node)
    main = max(candidates, key=lambda el: len(el.get_text(" ", strip=True))) if candidates else soup.body or soup

    for unwanted in main.select("script, style, noscript, nav, footer, header, form, aside"):
        unwanted.decompose()

    paragraphs = []
    for tag in main.find_all(["p", "h2", "h3", "li"]):
        text = tag.get_text(" ", strip=True)
        if text and len(text) > 2:
            paragraphs.append(text)
    body_text = "\n".join(paragraphs).strip()

    media: List[Dict[str, str]] = []
    for img in main.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        abs_src = absolutize(src, base_url)
        if detect_media_type(abs_src) == "image":
            media.append({"type": "image", "src": abs_src})

    for video in main.find_all("video"):
        vsrc = video.get("src")
        if vsrc:
            abs_src = absolutize(vsrc, base_url)
            if detect_media_type(abs_src) == "video":
                media.append({"type": "video", "src": abs_src})
        for source in video.find_all("source"):
            ssrc = source.get("src")
            if not ssrc:
                continue
            abs_src = absolutize(ssrc, base_url)
            if detect_media_type(abs_src) == "video":
                media.append({"type": "video", "src": abs_src})

    seen = set()
    uniq_media: List[Dict[str, str]] = []
    for item in media:
        key = (item["type"], item["src"])
        if key in seen:
            continue
        seen.add(key)
        uniq_media.append(item)

    return {"title": title, "text": body_text, "media": uniq_media}


def _simple_sentence_split(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def _fallback_summarize(text: str, target_words: int) -> str:
    sentences = _simple_sentence_split(text)
    collected: List[str] = []
    total = 0
    for sentence in sentences:
        words = len(sentence.split())
        if total + words > target_words:
            break
        collected.append(sentence)
        total += words
    if not collected:
        tokens = text.split()
        collected = [" ".join(tokens[:target_words])]
    return " ".join(collected).strip()


def _summarize_with_openai(text: str, target_words: int, language: str = "pl") -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    prompt = (
        f"Streść poniższy tekst w języku {language} tak, aby mieścił się w około {target_words} słowach. "
        "Zachowaj najważniejsze fakty i klarowną narrację dla lektora newsowego.\n"
        "Na zakończenie dodaj informację na temat źródła czyli londynek.net \n\n"
        f"--- TEKST ---\n{text}\n--- KONIEC ---"
    )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=DEFAULT_MODEL_VERSION,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        try:
            import openai

            openai.api_key = api_key
            response = openai.chat.completions.create(
                model=DEFAULT_MODEL_VERSION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=150,
            )
            try:
                return response["choices"][0]["message"]["content"].strip()
            except Exception:
                return response.choices[0].message.content.strip()
        except Exception:
            return None


def summarize_to_duration(text: str, max_minutes: float = 2.0, wpm: int = 160, language: str = "pl") -> str:
    max_words = max(50, int(wpm * max_minutes * 0.9))
    summary = _summarize_with_openai(text, max_words, language=language)
    if summary:
        tokens = summary.split()
        if len(tokens) > max_words:
            return " ".join(tokens[:max_words])
        return summary
    return _fallback_summarize(text, max_words)


def scrap_page(url: str, language: str = "pl") -> Dict:
    html = fetch_html(url)
    article = extract_article(html, url)
    title = article.get("title") or "Materiał"
    full_text = (article.get("text") or "").strip()
    summary = summarize_to_duration(full_text, max_minutes=2.0, wpm=160, language=language)

    media_items: List[Dict[str, str]] = []
    for item in article.get("media", []):
        src = item.get("src") or ""
        mtype = item.get("type") or detect_media_type(src)
        if not src or mtype not in {"image", "video"}:
            continue
        clean_src = src.split(".webp")[0] if src.endswith(".webp") else src.split("?")[0]
        media_items.append({"type": mtype, "src": clean_src})

    return {
        "title": title,
        "text": summary or full_text,
        "media": media_items,
        "source_url": url,
    }


def ask_model_openai(system_prompt: str, user_prompt: str, temperature: float = 0.5) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Brak klucza OPENAI_API_KEY")
    client_new = None
    try:
        from openai import OpenAI  # type: ignore

        client_new = OpenAI(api_key=api_key)
    except ImportError:
        client_new = None

    if client_new is not None:
        try:
            response = client_new.chat.completions.create(
                model=DEFAULT_MODEL_VERSION,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            pass

    try:
        import openai  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Brak biblioteki 'openai'. Zainstaluj pakiet `openai` w środowisku aplikacji."
        ) from exc

    openai.api_key = api_key
    response = openai.chat.completions.create(
        model=DEFAULT_MODEL_VERSION,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()


__all__ = [
    "PROMPTS",
    "get_prompt_by_id",
    "scrap_page",
    "ask_model_openai",
    "synthesize_speech",
]


def synthesize_speech(
    text: str,
    *,
    voice: str = "pl-PL-Wavenet-A",
    speaking_rate: float = 1.0,
    audio_encoding: str = "MP3",
) -> bytes:
    """Generate speech audio using Google Cloud Text-to-Speech."""
    if not text.strip():
        raise ValueError("Tekst do syntezy nie może być pusty")

    if texttospeech is None:
        raise RuntimeError(
            "Brak biblioteki 'google-cloud-texttospeech'. Zainstaluj pakiet lub skonfiguruj środowisko."
        )

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice_params = texttospeech.VoiceSelectionParams(
        language_code=voice[:5],
        name=voice,
    )

    encoding_map = {
        "MP3": texttospeech.AudioEncoding.MP3,
        "LINEAR16": texttospeech.AudioEncoding.LINEAR16,
        "OGG_OPUS": texttospeech.AudioEncoding.OGG_OPUS,
    }
    encoding = encoding_map.get(audio_encoding.upper(), texttospeech.AudioEncoding.MP3)

    audio_config = texttospeech.AudioConfig(
        audio_encoding=encoding,
        speaking_rate=max(0.5, min(2.0, float(speaking_rate))),
    )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice_params,
        audio_config=audio_config,
    )
    return response.audio_content
