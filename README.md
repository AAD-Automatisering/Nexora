# Zonentra — Intelligent Building Management

Een lokaal, modulair gebouwbeheersysteem als native Home Assistant Custom Integration.
**Eén Home Assistant = één Zonentra = één gebouw**, met meerdere ruimtes en installaties.

Versie 0.1.2 implementeert uitsluitend fase 1: indeling, observatie en diagnostische
simulatie. Zonentra roept geen apparaatservices aan en wijzigt geen HVAC-, KNX-,
zonwerings- of ventilatie-instellingen. De 16 °C-vloerverwarmingsgrens blijft intact.
Bestaande VTherm-regeling en automations blijven zelfstandig werken.

## Installatie

Getest met Home Assistant **2026.10.1**; oudere versies zijn niet ondersteund of getest.
De runtime heeft geen aanvullende Python-requirements en vereist geen VTherm.

1. Kopieer `custom_components/zonentra` uit dit project naar
   `<Home Assistant config>/custom_components/zonentra`.
2. Herstart Home Assistant.
3. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen → Zonentra**.
4. Geef het gebouw een naam. Een tweede Zonentra-entry wordt geweigerd.
5. Open de integratieopties (het tandwiel) om de gebouwindeling te configureren.

Er is geen YAML nodig.

### Installeren via HACS (custom repository)

1. Open **HACS → ⋮ → Custom repositories / Aangepaste repositories**.
2. Voeg `https://github.com/AAD-Automatisering/Zonentra` toe met type **Integration**.
3. Zoek **Zonentra** en download de integratie zodra deze versie is gepubliceerd.
4. Herstart Home Assistant.
5. Voeg **Zonentra** toe via **Instellingen → Apparaten & diensten**.

HACS installeert en beheert de bestanden; de gebouwconfiguratie gebeurt vervolgens
via de Home Assistant-integratie. Opname in de standaard HACS-catalogus is hiervoor
niet nodig. Home Assistant 2026.10.1 is de ingestelde minimumversie.
De repository-URL hierboven is het nieuwe projectadres; gebruik deze nadat de
GitHub-repository is hernoemd en versie 0.1.2 is gepubliceerd.

### Oude testinstallatie vervangen

Deze testversie heeft een nieuwe Home Assistant-domain en integratiemap: `zonentra`.
Er is geen automatische migratie van de vorige testintegratie.

1. Noteer eventueel de huidige ruimte- en apparatuurkoppelingen.
2. Verwijder de oude Nexora-configuratie via **Instellingen → Apparaten & diensten**.
3. Verwijder de oude integratie via HACS (of de map `custom_components/nexora` bij
   handmatige installatie). Verwijder daarbij alleen de oude integratiebestanden.
4. Installeer Zonentra via de nieuwe repository zodra deze versie gepubliceerd is.
5. Herstart Home Assistant en voeg **Zonentra** toe. Configureer de gebouwindeling opnieuw.

De bestaande Mitsubishi-, KNX- en VTherm-entiteiten worden niet verwijderd.
Verwijzingen naar de oude diagnostische statussensor moeten opnieuw worden gekoppeld.

Bronnen: [HACS custom repositories](https://www.hacs.dev/docs/faq/custom_repositories/),
[repositorystructuur](https://www.hacs.dev/docs/publish/integration/) en
[HACS-manifest](https://hacs.dev/docs/publish/start/).

## Indeling configureren

Gebruik **Ruimte toevoegen of bewerken**, **Buitenunitgroep toevoegen of bewerken**
en **Apparatuur toevoegen of bewerken**. Selecteer een bestaand item of `Add new`.
Geef elk item een herkenbare naam. Zonentra maakt automatisch een uniek intern ID
aan; dit verschijnt niet in de formulieren en blijft behouden als je de naam wijzigt.
Bestaande, eerder handmatig ingevulde IDs blijven ook behouden. Alle wijzigingen worden pas opgeslagen via
**Opslaan**. Sluiten verwerpt de transactie.

Maak eerst ruimtes aan, daarna buitenunitgroepen, daarna apparatuur. Voor het
kantoor kunnen twee groepen met de namen `Buitenunit 1` en `Buitenunit 2` worden gemaakt. Koppel
elke binnenunit aan zijn werkelijke ruimte en buitenunit; Zonentra raadt die relatie
niet. Groepen modelleren maximaal één heat/cool-modus tegelijk.

Een ruimte heeft optioneel een aparte KNX-temperatuursensor, een climate-
ruimtecontroller (bijvoorbeeld VTherm) en een binary_sensor voor ruimtebezetting.
Registreer de fysieke Mitsubishi-climate als HVAC-apparatuur. Meerdere apparaten
per ruimte en groep zijn mogelijk. Floor heating, shading, ventilation en other
kunnen ook worden geregistreerd; buitenunitgroepen zijn uitsluitend voor HVAC.
Dit registreert entiteitkoppelingen, geen nieuwe bedienbare HA-apparaten.

Verwijder apparatuur eerst voordat een gebruikte groep of ruimte wordt verwijderd.
Bij bewerken kunnen optionele koppelingen worden gewist. Nieuwe koppelingen moeten
in HA bestaan; bestaande offline bronnen hoeven niet te worden verwijderd. De
gebouwnaam wordt bij setup vastgelegd; deze eerste Options Flow bewerkt de indeling.
Centrale alarmbezetting, CO₂, P1, PV en weercontext volgen in latere fases.

## Status en diagnostiek

Het Zonentra-gebouw krijgt één diagnostische **Status**-sensor:

| Status | Betekenis |
| --- | --- |
| read_only | Gekoppelde inputs zijn observeerbaar; ook geldig bij een leeg gebouw |
| degraded | Minstens één input ontbreekt, is unknown of unavailable |
| conflict | Apparaten in dezelfde buitenunitgroep melden zowel heat als cool |

Attributen tonen aantallen en `hold`-beslissingen met reason codes:
`foundation_read_only`, `source_unavailable`, `observed_group_conflict`.
Alle beslissingen zijn simulatie. Een conflict wordt gemeld, niet gecorrigeerd.
`read_only` is geen bewijs van temperatuurkwaliteit of optimaal gebouwgedrag.

Download diagnostiek via het integratiemenu. Namen, IDs en entiteitkoppelingen
worden geredigeerd; ruwe bronstates worden niet geëxporteerd. Voor debuglogging
kan de standaard HA-functie **Debuglogging inschakelen** worden gebruikt.
Ontkoppelen/herladen ruimt eventlisteners op; Zonentra pollt niet.

## Ontwikkelen en testen

Gebruik Python 3.14.2 of nieuwer. De dependencyversies zijn vastgelegd voor de
geteste HA-versie; runtime-installatie van Zonentra vereist deze testtools niet.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

Tests gebruiken de echte Home Assistant flow manager, state machine, sensorplatform
en lifecycle-fixtures. Ze controleren ook dat geen servicecalls plaatsvinden bij
setup, bronwijzigingen, unload en opnieuw laden. CI voert dezelfde checks op Linux
uit. Een praktische installatie-/UI-smoketest in uw eigen HA blijft nodig.

## Projectstructuur

```text
ARCHITECTURE.md                 keuzes, datamodellen, interfaces en bronnen
ROADMAP.md                      fases en exitcriteria
README.md                       installatie en gebruik
custom_components/zonentra/
  __init__.py                   setup/unload, runtime_data, subscriptions
  manifest.json                 custom integration metadata, singleton
  const.py                      domein en types
  config_flow.py                gebouwsetup en topologie-editor
  models.py                     pure, immutable topologie en validatie
  decision.py                   pure read-only simulator
  runtime.py                    HA-observatie en update-dispatch
  sensor.py                     diagnostische statussensor
  diagnostics.py                geredigeerde diagnostiekdownload
  strings.json                  UI-teksten
  translations/{en,nl}.json     lokale UI-vertalingen
tests/                          topologie-, flow- en lifecycle-tests
.github/workflows/tests.yml     test- en lintworkflow
hacs.json                       HACS-metadata en minimale HA-versie
requirements-test.txt           vastgelegde testomgeving
pyproject.toml                  Python-, pytest- en Ruff-configuratie
```

Zie [ARCHITECTURE.md](ARCHITECTURE.md) en [ROADMAP.md](ROADMAP.md) voor vervolgwerk.
Zonentra gebruikt MIT als projectlicentie. VTherm is als MIT-gelicentieerde referentie
onderzocht; er is geen VTherm-code gekopieerd en er is geen forkafhankelijkheid.
