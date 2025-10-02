
import requests
from typing import Optional, Dict
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, parse_qs
#, urlsplit, urlunsplit, quote, parse_qsl, urlencode
from pathlib import PurePosixPath

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VID_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

def fetch_html(page_url: str, timeout: int = 15) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NewsToVideoBot/1.0; +https://example.local)"
    }
    r = requests.get(page_url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text

def scrap_page(url: str, language: str = "pl") -> Dict:
    """
    Główny punkt: pobiera stronę, wyodrębnia tytuł/treść/media i tworzy streszczenie <= ~2 min.
    Zwraca dict zgodny z payloadem formularza.
    """
    html = fetch_html(url)
    data = extract_article(html, url)
    title = data.get("title") or "Materiał"
    full_text = (data.get("text") or "").strip()
    # print(f'\t\t\tscrap_page len={len(full_text)}')

    summary = summarize_to_duration(full_text, max_minutes=2.0, wpm=160, language=language)

    # Ułóż media w formacie modułu
    media_items = []
    for m in data.get("media", []):
        mtype = detect_media_type(m.get("src", ""))
        if mtype in ("image", "video"):
            if len(m["src"].split('.webp')) == 2:
                m_src = m["src"].split('.webp')[0]
            elif len(m["src"].split('?')) == 2:
                m_src = m["src"].split('?')[0]
            else:
                m_src = m["src"]
            
            media_items.append({"type": mtype, "src": m_src})

    return {
        "title": title,
        "text": summary or full_text,
        "media": media_items,
        "source_url": url,
    }

def extract_article(html: str, base_url: str) -> Dict:
    soup = BeautifulSoup(html, "html.parser")

    # Tytuł
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip() or title

    # Główna treść – heurystyki: <article>, [role=main], #content, .article, itp.
    main_nodes = []
    for sel in ["article", "[role=main]", "#content", ".content", ".article", ".post", ".entry-content", ".news", ".story"]:
        main = soup.select_one(sel)
        if main:
            main_nodes.append(main)
    main = max(main_nodes, key=lambda el: len(el.get_text(" ", strip=True))) if main_nodes else soup.body or soup

    # Usuń elementy niekontentowe
    for bad in main.select("script, style, noscript, nav, footer, header, form, aside"):
        bad.decompose()

    # Zbierz akapity
    paragraphs = []
    for p in main.find_all(["p", "h2", "h3", "li"]):
        txt = p.get_text(" ", strip=True)
        if txt and len(txt) > 2:
            paragraphs.append(txt)
    text = "\n".join(paragraphs).strip()

    # Media: img, video > source/src
    media = []
    # IMG
    for img in main.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        src_abs = absolutize(src, base_url)
        mtype = detect_media_type(src_abs)
        if mtype == "image":
            media.append({"type": "image", "src": src_abs})
    # VIDEO
    for v in main.find_all("video"):
        vsrc = v.get("src")
        if vsrc:
            v_abs = absolutize(vsrc, base_url)
            if detect_media_type(v_abs) == "video":
                media.append({"type": "video", "src": v_abs})
        for s in v.find_all("source"):
            ssrc = s.get("src")
            if ssrc:
                s_abs = absolutize(ssrc, base_url)
                if detect_media_type(s_abs) == "video":
                    media.append({"type": "video", "src": s_abs})

    # Dedup
    seen = set()
    uniq_media = []
    for m in media:
        key = (m["type"], m["src"])
        if key in seen:
            continue
        seen.add(key)
        uniq_media.append(m)

    return {"title": title, "text": text, "media": uniq_media}

def summarize_to_duration(text: str, max_minutes: float = 2.0, wpm: int = 160, language: str = "pl") -> str:
    """
    Zwraca streszczenie o długości celowanej do max_minutes przy zadanym tempie mowy (wpm).
    Zakładamy ~1 słowo = 1 token mowy.
    """
    target_words = max(50, int(wpm * max_minutes * 0.9))  # bufor na pauzy
    # Spróbuj modelu, fallback do prostego skrótu
    model_sum = _summarize_with_openai(text, target_words, language=language)
    if model_sum:
        # Przytnij, gdyby model poszedł za daleko
        words = model_sum.split()
        if len(words) > target_words:
            return " ".join(words[:target_words])
        return model_sum
    return _fallback_summarize(text, target_words)


def detect_media_type(path_or_url: str) -> Optional[str]:
    """
    Rozpoznaje typ pliku (image|video) dla ścieżek lokalnych i URL-i z dodatkowymi parametrami.
    Nie modyfikuje oryginalnego URL-a — jedynie analizuje część path i query.
    Obsługuje podwójne rozszerzenia (np. .jpg.webp) i data:URI.
    """
    if not path_or_url:
        return None
    s = path_or_url.strip()

    # data URI
    if s.startswith("data:"):
        header = s[5:].split(";", 1)[0].lower()
        if header.startswith("image/"):
            return "image"
        if header.startswith("video/"):
            return "video"

    # parse URL (lub potraktuj jako ścieżkę)
    try:
        u = urlparse(s)
        path = u.path or s
        query = u.query or ""
    except Exception:
        path, query = s, ""

    # usuń ewentualne pozostałości ?/# w path (na wszelki wypadek)
    path = path.split("?", 1)[0].split("#", 1)[0]


    # sprawdź sufiksy ścieżki (obsługa podwójnych rozszerzeń, np. .jpg.webp)
    suffixes = [ext.lower() for ext in PurePosixPath(path).suffixes]
    for ext in reversed(suffixes):
        if ext in IMG_EXT:
            return "image"
        if ext in VID_EXT:
            return "video"

    # spróbuj odczytać format z query: ?format=webp / ?ext=mp4
    try:
        params = parse_qs(query.lower())
        fmt_vals = (params.get("format") or params.get("ext") or [])
        if fmt_vals:
            f = fmt_vals[0].strip(".").lower()
            if f in {e.strip(".") for e in IMG_EXT}:
                return "image"
            if f in {e.strip(".") for e in VID_EXT}:
                return "video"
        # szybki fallback na tekstowe wystąpienia w query
        q = query.lower()
        if any(k in q for k in ("format=jpg", "format=jpeg", "format=png", "format=webp", "ext=jpg", "ext=jpeg", "ext=png", "ext=webp")):
            return "image"
        if any(k in q for k in ("format=mp4", "format=webm", "format=mkv", "ext=mp4", "ext=webm", "ext=mkv")):
            return "video"
    except Exception:
        pass

    # ostateczny fallback: szukaj rozszerzenia w całym path
    base = path.lower()
    if any(e in base for e in IMG_EXT):
        return "image"
    if any(e in base for e in VID_EXT):
        return "video"

    return None

def absolutize(url: str, base: str) -> str:
    try:
        return urljoin(base, url)
    except Exception:
        return url

def _summarize_with_openai(text: str, target_words: int, language: str = "pl") -> Optional[str]:
    """
    Opcjonalne użycie OpenAI (jeśli biblioteka i klucz są dostępne).
    Zwraca streszczenie lub None przy błędzie.
    """
    try:
        # Nowy klient
        try:
            import os
            from openai import OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return None
            client = OpenAI(api_key=api_key)
            prompt = (
                f"Streść poniższy tekst w języku {language} tak, aby mieścił się w około {target_words} słowach. "
                "Zachowaj najważniejsze fakty i klarowną narrację dla lektora newsowego.\n"
                "Na zakończenie dodaj informację na temat źródła czyli londynek.net \n\n"
                f"--- TEKST ---\n{text}\n--- KONIEC ---"
            )
            resp = client.chat.completions.create(
                model=DEFAULT_MODEL_VERSION,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return None

    except Exception:
        print('✨ stary model klienta z openAI ✨')
        # Spróbuj starego klienta, jeśli nowy zawiedzie
        import os
        import openai  # stary klient
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        openai.api_key = api_key
        prompt = (
            f"Streść poniższy tekst w języku {language} tak, aby mieścił się w około {target_words} słowach. "
            "Zachowaj najważniejsze fakty i klarowną narrację dla lektora newsowego.\n"
            "Na zakończenie dodaj informację na temat źródła czyli londynek.net \n\n"
            f"--- TEKST ---\n{text}\n--- KONIEC ---"
        )
        resp = openai.chat.completions.create (
            model=DEFAULT_MODEL_VERSION,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=150,
        )
        try:
            summary = resp["choices"][0]["message"]["content"].strip()
        except:
            summary = resp.choices[0].message.content.strip()

        return summary



def _fallback_summarize(text: str, target_words: int) -> str:
    # Prosta strategia: weź zdania po kolei aż do limitu słów
    sentences = _simple_sentence_split(text)
    out = []
    total = 0
    for s in sentences:
        w = len(s.split())
        if total + w > target_words:
            break
        out.append(s)
        total += w
    if not out:  # gdy pierwsze zdanie za długie
        words = text.split()
        out = [" ".join(words[:target_words])]
    return " ".join(out).strip()
