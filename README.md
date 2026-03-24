# 🎬 TV Factory - Selbstgehostetes IPTV & VOD Streaming System

Ein vollständiges, automatisiertes IPTV-Streaming-System für lokale Medien mit VOD-Unterstützung, EPG-Generierung und Xtream Codes API-Kompatibilität. Optimiert für Formuler Geräte (MyTVOnline3), Enigma2, VLC und SmartTVs.

**Zero-Config Installation**: Die Factory installiert automatisch alle Software-Pakete (ffmpeg, nginx, php).  
**Voraussetzung**: Die Medien-Ordner müssen vor dem ersten Start existieren (siehe [Verzeichnisstruktur](#-verzeichnisstruktur)).

## ✨ Features

- **📺 Live TV Kanäle** - Automatisches HLS-Streaming aus lokalen Medienordnern
- **🎞️ VOD System** - Filme & Serien mit TMDB-Metadaten (Poster, Cast, Trailer)
- **🔄 Shuffle-Kanäle** - Smarte Mix-Kanäle (z.B. "Die Simpsons 24/7", "Movies UHD")
- **📻 Radio Streaming** - Mit statischem Hintergrundbild und EPG
- **📋 EPG (XMLTV)** - Automatische Programm-Guide Generierung für 8+ Tage
- **🔗 Xtream Codes API** - Kompatibel mit Xstreamity, MyTVOnline3, TiviMate
- **🗄️ SQLite Datenbank** - Schnelle Indizierung aller Medien
- **⚡ FFmpeg HLS** - Hardware-accelerated Streaming (copy-codec)
- **🐧 Systemd Integration** - Automatische Service-Verwaltung

## 🛠️ Systemanforderungen

- **OS**: Debian 12 / Ubuntu 22.04+ (amd64/arm64)
- **RAM**: 2GB minimum, 4GB+ empfohlen (bei Transcoding)
- **Storage**: 
  - System: 10GB
  - Medien: Je nach Bibliothek (HDD/SSD empfohlen)
- **Netzwerk**: Gigabit LAN empfohlen für 4K-Streaming

### Automatische Software-Installation
**Die Factory installiert selbstständig:**
- `ffmpeg` & `ffprobe` (für HLS-Encoding)
- `nginx-full` (Webserver mit PHP-FPM)
- `php-sqlite3` (Datenbank-Backend)
- `python3-requests` (TMDB API)

*Manuelle `apt install` Befehle sind nicht nötig, aber root-Rechte werden vorausgesetzt.*

## 📁 Verzeichnisstruktur (VORAB ANLEGEN!)

**Wichtig**: Diese Ordner müssen vor dem ersten Factory-Start existieren und die Pfade in `tv_factory.py` angepasst werden:

```python
# In tv_factory.py - CONFIG anpassen:
MOVIES_ROOTS = [Path("/srv/media_hdd/filme")]      # DEIN Pfad hier
SERIES_ROOTS = [Path("/srv/media_hdd/serien")]     # DEIN Pfad hier
PICONS_ROOT = "/srv/media_hdd/picons"              # Logos hier ablegen

/srv/media_hdd/
├── hls/              # HLS-Stream Ausgabe (automatisch)
├── state/            # Status-Dateien für EPG
├── playlists/        # M3U Listen
├── picons/           # Kanal-Logos
├── filme/            # Filme (kategorisiert in Unterordner)
├── serien/           # Serien (Serienname/Staffel/Episoden)
├── xstreamity/       # VOD-Only Medien
│   ├── filme/
│   └── serien/
└── radio/            # Radio-Stationen
    ├── mouv/
    │   ├── mouv.jpg (Hintergrund)
    │   └── url.txt  (Stream-URL)
    └── generationfm/
        ├── generationfm.jpg
        └── url.txt

sudo cp tv_factory.py /usr/local/bin/
sudo chmod +x /usr/local/bin/tv_factory.py

📄 Lizenz
GPL-3.0 - Frei verwendbar für private Projekte.
🙏 Credits
FFmpeg Team
TMDB für Metadaten-API
Xtream Codes für API-Spezifikation
