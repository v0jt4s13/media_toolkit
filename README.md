# Projekt Media Toolkit

Samodzielna aplikacja Flask skupiona na narzędziach do pracy z multimediami. Oprócz modułu **audiototext** (kolejka transkrypcji, integracja z YouTube i Google Cloud Speech) udostępnia prosty panel **URL → Prompt** do pobrania artykułu, wyboru promptu i wysłania zapytania do modelu.

## Struktura

```
media_toolkit/
├── data_settings/
│   ├── .env
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

### Uruchomienie
## Media toolkit - how to install
1. Sklonuj aplikacje z github, Włącz wirtualne środowisko, zainstaluj zależności 
 - `pip install -r requirements.txt`
 - `pip install gunicorn flask google-cloud-speech google-cloud-storage yt-dlp python-dotenv bs4`).
2. Uzupełnij zmienne środowiskowe w `data_settings/.env` lub wskaż inny plik przez `MEDIA_TOOLKIT_ENV_FILE`.
3. Uruchom aplikację: `python3 -m media_toolkit`.
4. Zaloguj się jednym z kont (`admin`, `redakcja`, `ads`, `tester`, `fox`).

```
cd ~/project
git clone git@github.com:v0jt4s13/media_toolkit.git
cd media_toolkit
mkdir -p data_settings
nano data_settings/.env
nano data_settings/logowanieoauth-3e4ca3c928b5.json (googlecreditencial-file.json)
cd media_toolkit
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
python3 -m media_toolkit
```

## Komendy testowe do oceny systemu
# co słucha portów 8000/8001/8002 itd.
sudo ss -ltnp | egrep ':8000|:8001|:8002|:80|:443|gunicorn|nginx'
# procesy gunicorna (z pełną linią komend)
pgrep -laf gunicorn
# jednostki systemd zawierające gunicorn
systemctl list-units --type=service | grep -i gunicorn
systemctl list-unit-files | grep -i gunicorn
# jeśli kiedyś używałeś socket-activation
systemctl list-units --type=socket | grep -i gunicorn
sudo systemctl stop gunicorn-talk_to.service
sudo systemctl disable gunicorn-talk_to.service
sudo systemctl mask gunicorn-talk_to.service
# podgląd uruchomionych serwisow gunicorn
pgrep -laf gunicorn
# delikatne ubicie po porcie (np. 8001)
sudo fuser -k 8001/tcp
# albo po nazwie – najpierw obejrzyj, potem (ostrożnie) kill:
pgrep -laf gunicorn
# jeśli pewny:
# sudo pkill -TERM -f 'gunicorn.*8001'

## Porządek i test po zmianach
# jeżeli usuwałeś/zmieniałeś unit pliki
sudo systemctl daemon-reload
# sanity check nginx (już masz prostą konfigurację, ale warto):
sudo nginx -t && sudo systemctl reload nginx
# strawdzenie aktywnych usług
systemctl list-units --type=service | egrep -i 'gunicorn|nginx'
systemctl list-unit-files | egrep -i 'gunicorn|nginx'



## Logi
Pliki logów znajdują się w `media_toolkit/media_toolkit/logs/` (rotowane za pomocą `RotatingFileHandler`).
sudo chown -R www-data:www-data /home/wmarzec/projects/media_toolkit/media_toolkit/logs



## Ustawienia konfiguracyjne gunicorn service
## /etc/systemd/system/gunicorn_media_toolkit.service
```
## Editing /etc/systemd/system/gunicorn_media_toolkit.service.d/override.conf
### Anything between here and the comment below will become the new contents of the file
[Service]
Environment="MEDIA_TOOLKIT_URL_PREFIX=/media_toolkit"
### Lines below this comment will be discarded
### /etc/systemd/system/gunicorn_media_toolkit.service
# [Unit]
# Description=Gunicorn for media_toolkit
# After=network.target
# [Service]
# User=www-data
# Group=www-data
# WorkingDirectory=/home/wmarzec/projects/media_toolkit
# Environment="PATH=/home/wmarzec/projects/media_toolkit/media_toolkit/venv/bin"
# Environment="MEDIA_TOOLKIT_URL_PREFIX="
# ExecStart=/home/wmarzec/projects/media_toolkit/media_toolkit/venv/bin/gunicorn \
#   --chdir /home/wmarzec/projects/media_toolkit \
#   -w 2 -b 127.0.0.1:8000 --timeout 240 wsgi:app
# Restart=on-failure
# RestartSec=5
# [Install]
# WantedBy=multi-user.target
```






# Projekt Moderacja LDNK
URL projektu:
git@github.com:v0jt4s13/moderacja_ldnk.git
Katalog projektu:
@ops01:{os.environ.get('HOME')}/projects/talk_to/
Bezpieczny deploy plików wraz z restartem usługi gunicorn:
@ops01:{os.environ.get('HOME')}/projects-github$ ./deploy-moderacja_ldnk.sh
Katalog templates z plikami html:
@ops01:{os.environ.get('HOME')}/projects/talk_to/templates/

Katalog `ai_moderation` zawiera niezależny projekt to automatycznego sprawdzania ogłoszeń.
Uruchomienie: 
# tryb testowy - 1 ogłoszenie   : python main.py accommodation 1234
# tryb testowy - cały dział     : python main.py accommodation
# tryb testowy - wszystkie diały: python main.py
# ai_moderation/start_job.sh - uruchamianie po kolei sekcji


mkdir ai_content_agent/results
mkdir ai_moderation/results
mkdir data_settings
touch data_settings/.env
touch data_settings/.env-ai_moderation
touch data_settings/texttoseech-456914-6a10db5d3e96.json
touch data_settings/tts_config.json


sudo apt update
sudo apt install libpq-dev python3-dev



mkdir {os.environ.get('HOME')}/logs/moderation/
sudo touch {os.environ.get('HOME')}/logs/moderation/ai_moderation_debug_logs.log
sudo touch {os.environ.get('HOME')}/logs/moderation/ads_moderation_debug_log.log
sudo touch {os.environ.get('HOME')}/logs/moderation/forum_moderate_debug_cron.log
sudo touch {os.environ.get('HOME')}/logs/moderation/ai_moderation_forum_log.log
sudo chown -R www-data:www-data {os.environ.get('HOME')}/logs/moderation/
sudo chmod 664 {os.environ.get('HOME')}/logs/moderation/*
sudo chmod +x {os.environ.get('HOME')}/projects/talk_to/run_*



### Pakiety - do zainstalowania
pip install markupsafe flask requests python-dotenv bs4 playwright boto3 openai psycopg2 filelock bleach

pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib google-cloud-texttospeech

pip install azure-cognitiveservices-vision-computervision azure-cognitiveservices-vision-customvision azure-cognitiveservices-speech

## Dodatkowe pakiety dla speech to text
pip install --upgrade google-cloud-speech google-api-core
## pakiety dla youtube
pip install yt-dlp

# Debian/Ubuntu - install codecs
sudo apt-get update && sudo apt-get install -y ffmpeg

## Dodatkowe biblioteki dla news to video
pip install moviepy 
pip install pydub
pip install python-slugify

## Logi - logowanie błędów logging (.info. .error)
sudo mkdir -p /var/log/talk_to
sudo chown www-data:www-data /var/log/talk_to
sudo chmod 750 /var/log/talk_to

### Media toolkit jako osobna aplikacja Flask
- Wymaga tych samych zmiennych środowisk co wersja zintegrowana (np. `FLASK_SECRET_KEY`, `ADMIN_PASSWORD`, dostęp do Google STT).
- Uruchom wirtualne środowisko i wywołaj `python3 -m audiototext`; aplikacja znajdzie wolny port lub użyje `FLASK_PORT`/`PORT`.
- Logowanie odbywa się tymi samymi kontami (`admin`, `redakcja`, `ads`, `tester`, `fox`). Po zalogowaniu strona główna przekierowuje na `/audiototext/` z formularzem.
- Konfiguracja środowiskowa wczytywana jest przez `audiototext/config.py` (wspiera zmienną `AUDIOTOTEXT_ENV_FILE` jeśli chcesz wskazać inny `.env`).
