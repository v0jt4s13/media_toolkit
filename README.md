# Media Toolkit

Samodzielna aplikacja Flask skupiona na narzędziach do pracy z multimediami. Oprócz modułu **audiototext** (kolejka transkrypcji, integracja z YouTube i Google Cloud Speech) udostępnia prosty panel **URL → Prompt** do pobrania artykułu, wyboru promptu i wysłania zapytania do modelu.

## Struktura

```
media_toolkit/
├── media_toolkit/
│   ├── __init__.py        # fabryka aplikacji Flask
│   ├── __main__.py        # `python3 -m media_toolkit` uruchamia serwer
│   ├── auth.py            # dekorator login_required i definicje użytkowników
│   ├── config.py          # wczytywanie .env (.env można nadpisać przez MEDIA_TOOLKIT_ENV_FILE)
│   ├── loggers.py         # prosta konfiguracja loggerów i helper `logger`
│   ├── content.py         # blueprint formularza URL → prompt (scraping + zapytania do LLM)
│   ├── templates/         # szablony bazowe, logowanie, błędy, widoki audiototext i content
│   └── audiototext/       # blueprint z trasami, zadaniami, usługami GCS/STT
│       ├── routes.py
│       ├── tasks.py
│       ├── service.py
│       ├── google_speech.py
│       ├── google_stt.py
│       └── gcs.py
└── README.md
```

Katalogi `media_toolkit/audiototext/{uploads,results,jobs}` są tworzone automatycznie podczas importu modułu.
Wyniki modułu **URL → Prompt** (transkrypcje i opcjonalne audio TTS) zapisywane są w `media_toolkit/media_toolkit/output/<użytkownik>/` i są dostępne wyłącznie dla zalogowanego użytkownika.

## Uruchomienie

1. Włącz wirtualne środowisko i zainstaluj zależności (`pip install flask google-cloud-speech google-cloud-storage yt-dlp python-dotenv bs4`).
2. Uzupełnij zmienne środowiskowe w `data_settings/.env` lub wskaż inny plik przez `MEDIA_TOOLKIT_ENV_FILE`.
3. Uruchom aplikację: `python3 -m media_toolkit`.
4. Zaloguj się jednym z kont (`admin`, `redakcja`, `ads`, `tester`, `fox`).

## Logi

Pliki logów znajdują się w `media_toolkit/media_toolkit/logs/` (rotowane za pomocą `RotatingFileHandler`).
