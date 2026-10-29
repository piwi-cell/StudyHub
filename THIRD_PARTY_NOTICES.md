# Drittsoftware

StudyHub selbst steht unter „Alle Rechte vorbehalten“ (siehe `LICENSE`). Die folgenden Bestandteile
stammen von anderen und stehen unter ihren eigenen Lizenzen. Die Angaben stammen aus den Paketangaben
(Stand: `uv.lock`, 29.10.2026); maßgeblich ist jeweils der Lizenztext des Projekts.

## Mitgeliefert

| Bestandteil | Version | Lizenz | Ort |
|---|---|---|---|
| ElevenLabs JavaScript-Client (`@elevenlabs/client`) | 1.27.0 | MIT, © 2025 ElevenLabs | `ui/vendor/elevenlabs-client-1.27.0/` (mit Lizenztext) |

## Bei der Installation geladen

`scripts/install.sh` bzw. `scripts/setup.sh` laden diese Programme von ihren offiziellen Quellen auf den
Mac; sie sind nicht Teil des Projekts.

| Programm | Lizenz | Quelle |
|---|---|---|
| uv (Paketverwaltung) | MIT oder Apache-2.0 | github.com/astral-sh/uv |
| Python 3.13 (über uv, python-build-standalone) | PSF-2.0 und die Lizenzen der enthaltenen Bibliotheken | python.org, github.com/astral-sh/python-build-standalone |

### Python-Pakete

PFERD (Programm zum Abruf der ILIAS-Dateien, github.com/Garmelon/PFERD) wird unverändert installiert;
`core/pferd_runner.py` passt einzelne Funktionen erst zur Laufzeit an.

| Paket | Version | Lizenz |
|---|---|---|
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache-2.0 |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anthropic | 2.3.0 | Apache-2.0 |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| beautifulsoup4 | 4.15.0 | MIT |
| bottle | 0.13.4 | MIT |
| certifi | 2026.10.23 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.0 | BSD-3-Clause |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| docstring-parser | 0.18.0 | MIT |
| fastapi | 0.162.0 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpcore2 | 2.16.0 | BSD-3-Clause |
| httptools | 0.9.0 | MIT |
| httpx2 | 2.16.0 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| jaraco-classes | 3.4.0 | MIT |
| jaraco-context | 6.1.2 | MIT |
| jaraco-functools | 4.6.0 | MIT |
| jiter | 0.18.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| keyring | 25.7.0 | MIT |
| markdown-it-py | 4.2.0 | MIT |
| mcp | 2.3.0 | MIT |
| mcp-types | 2.3.0 | MIT |
| mdurl | 0.1.2 | MIT |
| more-itertools | 11.2.1 | MIT |
| multidict | 7.2.0 | Apache-2.0 |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pferd | 3.9.4 | MIT |
| propcache | 0.5.4 | Apache-2.0 |
| proxy-tools | 0.1.0 | MIT |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| pydantic-core | 2.50.1 | MIT |
| pyjwt | 2.15.1 | MIT |
| pyobjc-core | 12.2.2 | MIT |
| pyobjc-framework-cocoa | 12.2.2 | MIT |
| pyobjc-framework-quartz | 12.2.2 | MIT |
| pyobjc-framework-security | 12.2.2 | MIT |
| pyobjc-framework-uniformtypeidentifiers | 12.2.2 | MIT |
| pyobjc-framework-webkit | 12.2.2 | MIT |
| pypdf | 6.21.2 | BSD-3-Clause |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| pywebview | 6.2.1 | BSD |
| pyyaml | 6.0.3 | MIT |
| referencing | 0.37.0 | MIT |
| rich | 15.0.0 | MIT |
| rpds-py | 2026.9.1 | MIT |
| sniffio | 1.3.1 | MIT / Apache-2.0 |
| soupsieve | 3.0.4 | MIT |
| sse-starlette | 3.5.1 | BSD-3-Clause |
| starlette | 1.9.0 | BSD-3-Clause |
| truststore | 0.10.5 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| uvloop | 0.23.0 | Apache-2.0 / MIT |
| watchfiles | 1.3.0 | MIT |
| websockets | 17.3 | BSD-3-Clause |
| yarl | 1.25.1 | Apache-2.0 |


Nur zum Entwickeln (`scripts/setup.sh` ohne `--app`), nicht in der installierten App:

| Paket | Version | Lizenz |
|---|---|---|
| httpx | 0.28.1 | BSD |
| iniconfig | 2.3.1 | MIT |
| pluggy | 1.7.0 | MIT |
| pygments | 2.21.0 | BSD-2-Clause |
| pytest | 9.1.1 | MIT |
| ruff | 0.17.2 | MIT |

Nur auf anderen Systemen (Windows, Linux) vorgesehen, auf dem Mac nicht installiert: clr-loader, colorama,
httpx2-jsfetch, jeepney, pythonnet, pywin32, pywin32-ctypes, qtpy, secretstorage.

## Nicht enthalten

Ollama und die Gemma-Modelle installiert man selbst (ollama.com); für Gemma gelten die Gemma-Nutzungsbedingungen
von Google. Die KI-Dienste (Anthropic, OpenAI, Google, ElevenLabs) nutzt man mit eigenem API-Key unter deren
Bedingungen.
