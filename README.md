# Zonentra — Intelligent Building Management

Een lokaal, modulair gebouwbeheersysteem als native Home Assistant Custom Integration.
**Eén Home Assistant = één Zonentra = één gebouw**, met meerdere ruimtes en installaties.

Versie **0.2.0** voegt uitlegbare klimaatvraag per ruimte en gewogen
buitenunitvoorstellen toe, volledig in read-only simulatie. Zonentra roept geen apparaatservices aan en wijzigt geen HVAC-, KNX-,
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
Na publicatie van deze versie kan HACS de bijgewerkte bestanden downloaden.
De lokale wijziging op zichzelf publiceert nog geen GitHub-release.

### Bijwerken vanaf Zonentra 0.1

Werk de bestaande integratie bij via HACS en herstart Home Assistant. **Verwijder
je bestaande Zonentra-configuratie niet.** Het domain, de opgeslagen structuur,
IDs, apparaatkoppelingen en de Status-sensor blijven behouden. De nieuwe velden
zijn additief en hebben achterwaarts compatibele modeldefaults: er is geen
config-entry-versiemigratie nodig (Config Flow VERSION blijft 1).

Open daarna Opties, bewerk iedere ruimte en configureer de twee klimaatgrenzen.
Een oude ruimte zonder klimaatgrenzen blijft laden maar heeft demand=unknown.
Er wordt geen VTherm-setpoint automatisch als verwarmings- én koelgrens gebruikt.
De veel eerdere testintegratie onder domain `nexora` is een andere integratie;
zoals afgesproken bij de naamswijziging is daarvoor geen migratie toegevoegd.

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
Centrale alarmmapping, ventilatie-/CO₂-regeling, P1/PV en weeroptimalisatie volgen
in latere fases. Optionele CO₂ en buitentemperatuur kunnen nu al als context worden gekoppeld.

## Klimaatintelligentie configureren

Bewerk een ruimte via **Opties → Ruimte toevoegen of bewerken**:

| Veld | Gebruik / voorgestelde beginwaarde |
|---|---|
| Ruimtetemperatuursensor | De externe KNX-temperatuursensor, met °C of °F |
| Verwarmingsgrens / koelgrens | Bijvoorbeeld 21 / 24 °C; analysegrenzen, geen apparaat-setpoints |
| Grensentiteiten | Optionele sensor/number/input_number met °C/°F; gaan vóór vaste grenzen |
| Ruimteweging | 1; grotere of belangrijkere ruimtes kunnen zwaarder meewegen |
| Temperatuurhysterese | 0,3 °C; ruimte tussen grenzen moet groter zijn dan tweemaal hysterese |
| Maximale meetleeftijd | 1800 s; afstemmen op de werkelijke sensorrapportage, 0 schakelt de check uit |
| Buitenunitgroep | Optioneel als standaard voor HVAC-apparatuur in deze ruimte |
| Optionele context | Vochtigheid, CO₂, aanwezigheid, raam-/deurcontacten, buitentemperatuur |

De VTherm-climate blijft de ruimteregelaar; registreer de fysieke Mitsubishi-climate
als HVAC-apparatuur. Een expliciete groep bij een apparaat mag niet afwijken van
de groep van de ruimte. Meerdere binnenunits in dezelfde ruimte tellen in de
vraagscore van hun groep maar één keer mee.

Bewerk vervolgens een **Buitenunitgroep**:

- **Actuele modus-feedback:** alleen een betrouwbare entiteit die de actuele modus
  van de gedeelde installatie meldt als `heat`, `cool` of `off`. Selecteer hier
  niet zonder verificatie de gewenste VTherm-modus. Heb je geen betrouwbare
  terugmelding, laat de bron leeg: desired kan berekend worden, proposed blijft
  unknown en `current_mode_unknown` verklaart de blokkering.
- **Minimuminterval:** 900 s tussen waargenomen modusveranderingen. Herstart en
  options-reload beginnen conservatief met een nieuwe wachttijd.
- **Minimale vraagscore:** 0,5. **Minimaal scoreverschil:** 0,5 om heen-en-weer
  wisselen bij kleine verschillen tussen warmte- en koelvraag te beperken.
- **Feedbackleeftijd:** 1800 s, afstemmen op de bron. Ook actuele modusfeedback
  kan verouderen.

Klik tenslotte **Opslaan**. De ingestelde analysegrenzen wijzigen geen airco- of
vloerverwarmingssetpoints. Optionele aanwezigheid ontbreekt → unknown, nooit away.
Optionele context beïnvloedt de klimaatscores in 0.2 nog niet.

## Status en diagnostiek

Er zijn **één gebouwsensor, één klimaatsensor per ruimte en één modusvoorstelsensor
per buitenunitgroep**. Scores en verklaringen staan in compacte attributen, zodat
niet voor elke score een aparte entiteit nodig is.

| Sensor | State | Belangrijkste attributen |
|---|---|---|
| Status | read_only / degraded / conflict | zones, groups, equipment, unavailable_inputs, unknown_zone_demands; maximaal 20 fysieke hold-beslissingen |
| Ruimte Klimaatvraag | heating_demand / cooling_demand / neutral / unknown | temperature_c, heating_limit_c, cooling_limit_c, heating_score, cooling_score, reason, sensor_health, source_health, occupancy |
| Buitenunit Voorgestelde HVAC-modus | heat / cool / off / unknown | current_mode, desired_mode, heating_score, cooling_score, reason, blocked_reason, blocked_until, mode_change_proposed, mode_quality, reliable_zones |

`read_only` bevestigt observatie/simulatie, ook bij een leeg gebouw. `degraded`
betekent een ontbrekende/unknown/unavailable gekoppelde bron of een ongeldige
klimaatvraag voor een ruimte met ingestelde grenzen. Optionele bronproblemen zijn
zichtbaar, maar blokkeren de vraagberekening niet. `conflict` meldt tegengestelde
heat/cool-states van binnenunits binnen dezelfde beperkte groep.

`proposed_mode` is wat na alle controles voorgesteld mag worden: bij een bekende
actuele modus en een nog lopende wachttijd blijft hij op current_mode. De gewenste
richting blijft afzonderlijk zichtbaar in desired_mode. `unknown` betekent geen
bruikbaar voorstel; kijk dan naar blocked_reason. `off` is een simulatie van geen
actieve vraag, nooit een uitschakelcommando. De fysieke hold-beslissingen op de
Status-sensor blijven voor alle apparatuur gelden.

Sensor health: valid, missing, unknown, unavailable, stale of unreliable. Scores
zijn gewogen graden afwijking, geen energie- of vermogensmetingen. Afwezige
klimaatdata geven null-scores, geen verzonnen nulvraag. Zie
[ALGORITHM.md](ALGORITHM.md) voor alle formules, drempels en reden-codes.

Download diagnostiek via het integratiemenu. Namen, IDs en bronkoppelingen worden
geredigeerd. De export bevat scores en verklaringen, geen ruwe sensorstates.
Debuglogging kan via de standaard HA-functie worden ingeschakeld. Bronlisteners
volgen wijzigingen én rapporten met dezelfde waarde; één deadline-timer houdt
sensorleeftijd en wachttijden bij. Er is geen periodieke polling.

## Veilig testen naast VTherm

Laat de bestaande regeling en automations gewoon draaien. Vergelijk per ruimte
de KNX-temperatuur, ingestelde analysegrenzen en weergegeven klimaatscores.
Controleer per buitenunit current/desired/proposed en de blokkeerreden. Test een
onbeschikbare bron en het herstel daarvan; Zonentra moet unknown melden in plaats
van een nieuwe modus bedenken. **Koppel de voorgestelde modi niet aan eigen
actuator-automations** als je deze versie read-only wilt testen.

Aanwezigheid, ramen, vloerverwarming, zonwering en ventilatie worden niet bediend.
De gasvloergrens van 16 °C blijft intact. Een HA-herstart moet bij een bekend
modusverschil weer een omschakelwachttijd laten zien.

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

De suite omvat 79 tests. Pure kernfuncties worden zonder HomeAssistant-instance
getest. Integratietests gebruiken de echte Home Assistant flow manager, state machine, sensorplatform
en lifecycle-fixtures. Ze controleren ook dat geen servicecalls plaatsvinden bij
setup, bronwijzigingen, unload en opnieuw laden. CI voert dezelfde checks op Linux
uit. Een praktische installatie-/UI-smoketest in uw eigen HA blijft nodig.

## Projectstructuur

```text
ARCHITECTURE.md                 keuzes, datamodellen, interfaces en bronnen
ROADMAP.md                      fases en exitcriteria
README.md                       installatie en gebruik
ALGORITHM.md                    formules, bronkwaliteit en omschakelbeveiliging
custom_components/zonentra/
  __init__.py                   setup/unload, runtime_data, subscriptions
  manifest.json                 custom integration metadata, singleton
  const.py                      domein en types
  config_flow.py                gebouwsetup en topologie-editor
  models.py                     pure, immutable topologie en validatie
  observations.py               bronkwaliteit, leeftijd en eenheden
  demand.py                     ruimtesnapshots en klimaatvraag
  engine.py                     gewogen groepsarbitrage en verklaringen
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
