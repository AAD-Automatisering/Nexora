# Zonentra — Intelligent Building Management

Een lokaal, modulair gebouwbeheersysteem als native Home Assistant Custom Integration.
**Eén Home Assistant = één Zonentra = één gebouw**, met meerdere ruimtes en installaties.

Versie **0.5.0** simuleert de volledige regelstrategie: per buitenunitgroep een
leidende modus met een veilige omschakelprocedure, per binnenunit de actie die
Zonentra zou nemen (verwarmen, koelen, uit, modus corrigeren, ongewijzigd of
geblokkeerd), handmatige bediening via de KNX-roomcontroller (Manual Override,
standaard 30 minuten) en anti-pendelbeveiliging. **Er wordt niets aangestuurd:**
alle acties zijn zichtbaar als simulatie. Versie 0.4.0 observeert de bestaande binnenunits (climate-entiteiten): per
binnenunit de ingestelde modus en `hvac_action`, en per buitenunitgroep een
**afgeleide** groepsmodus met conflictdetectie, naast de gewenste modus uit de
klimaatvraag. Een afgeleide modus is nooit fysieke buitenunitfeedback. Versie
0.3.1 herstelde de sensorvalidatie: een geldige temperatuur die lang niet
verandert (zoals bij KNX) wordt niet langer onterecht `stale`. Versie 0.3.0
voegde centrale gebouwinstellingen met optionele ruimteafwijkingen toe aan de
uitlegbare klimaatvraag en gewogen buitenunitvoorstellen. Alles blijft
read-only simulatie. Zonentra roept geen apparaatservices aan en wijzigt geen HVAC-, KNX-,
zonwerings- of ventilatie-instellingen. De 16 °C-vloerverwarmingsgrens blijft intact.
Bestaande regelingen en automations blijven zelfstandig werken.

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

### Bijwerken naar 0.5.0

Werk bij via HACS en herstart Home Assistant; herconfiguratie is niet nodig.
Bestaande configuraties krijgen de standaardinstellingen voor handmatige
bediening en anti-pendel (zie **Opties → Centrale configuratie**). Per binnenunit
en per buitenunitgroep verschijnt een nieuwe simulatiesensor. Herlaad daarna de
browserpagina volledig, zodat de nieuwe vertalingen worden geladen.

### Bijwerken naar 0.4.0

Werk bij via HACS en herstart Home Assistant; herconfiguratie is niet nodig.
Binnenunits zijn de climate-entiteiten die al als **HVAC-apparatuur** aan een
ruimte zijn gekoppeld. Voor elke binnenunit en elke buitenunitgroep verschijnen
automatisch nieuwe diagnostische sensoren.

### Bijwerken naar 0.3.1

Werk bij via HACS en herstart Home Assistant; herconfiguratie is niet nodig.
Bestaande ruimtes en centrale instellingen zonder validatiestrategie gebruiken
automatisch `state_based`: een geldige, beschikbare temperatuur blijft bruikbaar,
ook als hij uren niet verandert. Een eerder ingestelde maximale meetleeftijd blijft
bewaard en wordt pas actief als je bewust `update_based` kiest (zie
[ALGORITHM.md](ALGORITHM.md#validatiestrategie-031)).

### Bijwerken vanaf Zonentra 0.1 of 0.2

Werk de bestaande integratie bij via HACS zodra 0.3.x is gepubliceerd en herstart
Home Assistant. **Verwijder je bestaande Zonentra-configuratie niet.** De automatische
migratie naar configuratieversie 3 behoudt IDs, apparaatkoppelingen en sensoren.
Bestaande eigen analysegrenzen, hysterese en meetleeftijd blijven actief als lokale
instellingen. Nieuwe ruimtes gebruiken standaard de centrale instellingen.

De vroegere `controller_entity`-koppeling wordt bij migratie verwijderd. Zonentra
heeft geen ruimteregelaar of VTherm nodig: de externe temperatuur en analysegrenzen
bepalen de vraag. Een ontbrekende oude thermostaat telt niet meer als bronprobleem.

Een bestaande buitentemperatuurbron wordt naar het gebouw verplaatst. Wanneer
verschillende ruimtes verschillende bronnen hadden, kiest Zonentra geen bron:
selecteer de juiste via **Opties → Centrale configuratie**. De kandidaten staan
in het formulier; Status meldt `outdoor_temperature_selection_required`.

Oude ruimtes zonder grenzen blijven unknown zolang geen centrale grenzen zijn
opgeslagen. Configureer centraal de gewenste grenzen en vink bij bestaande ruimtes
**Centrale klimaatgrenzen gebruiken** aan om ze over te nemen. De veel eerdere
testintegratie onder domain `nexora` heeft geen migratie naar `zonentra`.

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

Stel eerst de centrale configuratie in, maak daarna ruimtes, buitenunitgroepen en apparatuur aan. Voor het
kantoor kunnen twee groepen met de namen `Buitenunit 1` en `Buitenunit 2` worden gemaakt. Koppel
elke binnenunit aan zijn werkelijke ruimte en buitenunit; Zonentra raadt die relatie
niet. Groepen modelleren maximaal één heat/cool-modus tegelijk.

Een ruimte heeft optioneel een aparte KNX-temperatuursensor en een binary_sensor
voor ruimtebezetting.
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

Begin via **Opties → Centrale configuratie**:

| Centrale instelling | Gebruik / voorgestelde beginwaarde |
|---|---|
| Buitentemperatuursensor | Eén sensor voor het hele gebouw, met °C of °F |
| Maximale leeftijd buitentemperatuur | 1800 s; onafhankelijk van de ruimtesensoren |
| Verwarmingsgrens / koelgrens | 21 / 24 °C; analysegrenzen, geen apparaat-setpoints |
| Grensentiteiten | Optionele sensor/number/input_number met °C/°F; gaan vóór vaste grenzen |
| Temperatuurhysterese | 0,3 °C; ruimte tussen grenzen groter dan tweemaal hysterese |
| Sensorvalidatie | `state_based` (standaard): geldige state is bruikbaar, geen leeftijdcontrole. `update_based`: alleen voor bronnen die aantoonbaar periodiek rapporteren |
| Maximale updateleeftijd | 1800 s; alleen actief bij `update_based` (moet dan > 0 zijn) |
| Handmatige bediening toestaan | Aan; Manual Override via de roomcontroller (simulatie) |
| Duur handmatige bediening | 30 minuten (5–120) |
| Minimale inschakeltijd | 600 s (comfort) |
| Minimale uitschakeltijd | 180 s (veiligheid; controleer fabrikant) |
| Wachttijd groepsomschakeling | 300 s (veiligheid; tussen stoppen en tegengestelde modus) |

Bewerk daarna een ruimte via **Opties → Ruimte toevoegen of bewerken**:

| Ruimte-instelling | Gebruik |
|---|---|
| Ruimtetemperatuursensor | De externe KNX-temperatuursensor |
| Centrale klimaatgrenzen gebruiken | Standaard aan voor nieuwe ruimtes; neemt beide grenzen en grensentiteiten over |
| Centrale meetparameters gebruiken | Standaard aan; neemt hysterese, sensorvalidatie en maximale updateleeftijd over |
| Ruimteweging | Standaard 1; belangrijkere ruimtes kunnen zwaarder meewegen |
| Buitenunitgroep | Optionele standaard voor HVAC-apparatuur in deze ruimte |
| Optionele ruimtecontext | Vochtigheid, CO₂, aanwezigheid en raam-/deurcontacten |

Vink een centrale keuze uit en klik **Volgende** om de eigen velden te tonen.
De twee keuzes werken onafhankelijk. Terugschakelen naar centraal bewaart eerder
opgeslagen eigen waarden voor later, maar gebruikt ze niet als fallback wanneer
een centrale bron ontbreekt. Een wijziging centraal geldt voor alle ruimtes die
dat blok overnemen. De sensorattributen `limits_source` en `parameters_source`
tonen `building` of `zone`.

Deze opzet volgt het configuratieprincipe van VTherm: één centrale configuratie en
lokale instanties die parameterblokken overnemen. In Zonentra blijft alles binnen
één gebouw-entry. De fysieke climate-entiteit wordt als apparatuur aan een ruimte gekoppeld,
onafhankelijk van de centrale parameterkeuzes.

Registreer de fysieke Mitsubishi-climate als HVAC-apparatuur. Een expliciete groep bij een apparaat mag niet afwijken van
de groep van de ruimte. Meerdere binnenunits in dezelfde ruimte tellen in de
vraagscore van hun groep maar één keer mee.

Bewerk vervolgens een **Buitenunitgroep**:

- **Actuele modus-feedback:** alleen een betrouwbare entiteit die de actuele modus
  van de gedeelde installatie meldt als `heat`, `cool` of `off`. Selecteer hier
  niet zonder verificatie een gewenste modus. Heb je geen betrouwbare
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
Optionele context beïnvloedt de klimaatscores in 0.3 nog niet.

## Status en diagnostiek

Er zijn **één gebouwsensor, één klimaatsensor per ruimte, per binnenunit een
modus- en een gesimuleerde-actiesensor, en per buitenunitgroep een modusvoorstel-,
een afgeleide-modus- en een gesimuleerde-coördinatiesensor**. Scores en verklaringen staan in compacte attributen, zodat
niet voor elke score een aparte entiteit nodig is.

| Sensor | State | Belangrijkste attributen |
|---|---|---|
| Status | read_only / degraded / conflict | zones, groups, equipment, unavailable_inputs, unknown_zone_demands, outdoor_temperature_c, outdoor_temperature_quality, outdoor_temperature_validation, outdoor_temperature_freshness_verified, outdoor_temperature_selection_required; maximaal 20 fysieke hold-beslissingen |
| Ruimte Klimaatvraag | heating_demand / cooling_demand / neutral / unknown | temperature_c, heating_limit_c, cooling_limit_c, heating_score, cooling_score, reason, sensor_health, source_health, sensor_validation, temperature_validation, occupancy, limits_source, parameters_source |
| Buitenunit Voorgestelde HVAC-modus | heat / cool / off / unknown | current_mode, desired_mode, heating_score, cooling_score, reason, blocked_reason, blocked_until, mode_change_proposed, mode_quality, reliable_zones, physical_mode, mode_feedback_quality, physical_mode_feedback_available, derived_group_mode, observation_reason |
| Binnenunit-modus | heat / cool / heat_cool / auto / dry / fan_only / off / unknown | indoor_unit_entity, selected_mode, reported_action, current_temperature, target_temperature, temperature_unit, fan_mode, availability, observation_quality, selected_action_mismatch, observed_at |
| Buitenunit Modus afgeleid van binnenunits | heat / cool / inactive / mixed / unknown | member_indoor_units, available_indoor_units, usable_selected_modes, usable_hvac_actions, selected_modes, selected_mode_consensus, reported_activity, conflict_detected, conflicts, completeness, quality, reason, notes, desired_mode, physical_mode, physical_mode_feedback_available, observation_reason |

| Binnenunit Gesimuleerde actie | turn_on_heat / turn_on_cool / turn_off / correct_mode / hold / blocked | simulation, zone, observed_mode, desired_mode, zone_demand, intended_action, steps, reason, blocked_reason, blocked_until, manual_override_active, override_remaining_seconds, override_expires_at, seconds_since_transition, group_coordination_phase, availability, evaluated_at |
| Buitenunit Gesimuleerde coördinatie | idle / preparing / stopping / waiting / applying / verifying / completed / blocked / failed | simulation, desired_mode, group_mode, group_mode_reason, coordinated_mode, derived_mode, member_indoor_units, available_indoor_units, conflicts, switch_needed, switch_from, switch_to, switch_allowed_in_simulation, active_switch_permitted (altijd false), phase_reason, waiting_until, blockers, planned_actions |

### Gesimuleerde regeling en handmatige bediening (0.5)

De groepsmodus (heat / cool / neutral / unknown) volgt uit de bestaande gewogen
klimaatvraag en is leidend voor alle binnenunits in de groep. Per binnenunit:
warmtevraag → verwarmen, koelvraag → koelen, geen vraag → uit, verkeerde modus →
corrigeren, onvoldoende informatie → geblokkeerd.

**Handmatige bediening.** Zet een medewerker de airco via de KNX-roomcontroller
aan (`off` → actieve modus), dan start een Manual Override van standaard 30
minuten (5–120, centraal instelbaar of uit te zetten). De airco mag dan aan
blijven, maar de groepsmodus blijft leidend: `cool` in een `heat`-groep wordt
gecorrigeerd naar `heat`. Uitzetten beëindigt de override; daarna geldt de
normale regeling weer. Attribuutwijzigingen, herstarts en overgangen vanuit
`unknown`/`unavailable` starten nooit een override. Een override overleeft een
herstart niet. **Let op:** Home Assistant kan niet zien wie een state wijzigt;
ook een eigen automatisering die een airco aanzet, start een override.

**Anti-pendel en omschakeling.** Minimale aan-tijd (comfort, 600 s), minimale
uit-tijd (veiligheid, 180 s) en wachttijd bij heat↔cool (veiligheid, 300 s) zijn
centraal instelbaar; de bestaande groepsparameter "minimale tijd tussen
moduswisselingen" geldt ook hier. Controleer de veiligheidswaarden met de
Mitsubishi-documentatie. Een omschakeling doorloopt idle → preparing → stopping →
waiting → applying → verifying → completed, alleen op basis van waarnemingen.
Zonder aansturing blijft die in read-only bijvoorbeeld op `stopping` staan.

Details, alle reason codes en de beperkingen staan in
[ALGORITHM.md](ALGORITHM.md#gesimuleerde-regelstrategie-05).

### Binnenunits en afgeleide groepsmodus (0.4)

Koppel iedere bestaande airco-climate-entiteit via **Opties → Apparatuur** als
type `hvac` aan zijn ruimte; de buitenunitgroep volgt uit de ruimte. Meerdere
binnenunits per ruimte en per groep zijn mogelijk. Dezelfde entiteit kan maar
één keer gekoppeld worden; een tweede koppeling geeft een duidelijke foutmelding.
Wijzigen of ontkoppelen kan in hetzelfde formulier; overbodige sensoren worden
bij opslaan verwijderd.

Zonentra houdt drie dingen gescheiden:

- **Selected mode** – de ingestelde modus (de entity state, bijv. `heat`).
- **Reported action** – `hvac_action` zoals HA hem meldt (bijv. `idle`). Dat is
  alleen zo betrouwbaar als de onderliggende integratie; Zonentra neemt niet aan
  dat dit fysieke terugmelding is.
- **Physical mode** – alleen de expliciet ingestelde, betrouwbare modus-feedback
  van de groep. Zonder die bron blijft `physical_mode` `unknown` en blijft
  `current_mode_unknown` een moduswissel blokkeren, wat de binnenunits ook melden.

Voorbeeld: ruimte met warmtevraag, airco uit → desired `heat`, afgeleid
`inactive`, physical `unknown`, `observation_reason: heat_requested_units_inactive`.
De afleidingsregels en alle reason codes staan in [ALGORITHM.md](ALGORITHM.md#binnenunits-en-afgeleide-groepsmodus-04).

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

Sensor health: valid, missing, unknown, unavailable, stale of unreliable. Het
attribuut `temperature_validation` verklaart de temperatuurbron: `health`,
`strategy`, `value`, `reason` (waarom afgekeurd), `seconds_since_change`
(sinds `last_changed`), `seconds_since_report` (sinds `last_reported`),
`max_update_age_seconds`, `freshness_verified` en `evaluated_at`. Leeftijden
gelden op `evaluated_at`, het moment van de laatste evaluatie. Een stabiele
20,7 °C met `freshness_verified: false` is bruikbaar en **niet defect**: het
betekent alleen dat de bron geen periodieke rapportage levert om actualiteit te
bewijzen. De diagnostiekexport bevat dezelfde verklaring per bron, zonder waarden.
Scores
zijn gewogen graden afwijking, geen energie- of vermogensmetingen. Afwezige
klimaatdata geven null-scores, geen verzonnen nulvraag. Zie
[ALGORITHM.md](ALGORITHM.md) voor alle formules, drempels en reden-codes.

Download diagnostiek via het integratiemenu. Namen, IDs en bronkoppelingen worden
geredigeerd. De export bevat scores en verklaringen, geen ruwe sensorstates.
Debuglogging kan via de standaard HA-functie worden ingeschakeld. Bronlisteners
volgen wijzigingen én rapporten met dezelfde waarde; één deadline-timer houdt
sensorleeftijd (alleen update_based) en wachttijden bij. Er is geen periodieke polling.

## Veilig testen naast de bestaande regeling

Laat de bestaande regeling en automations gewoon draaien. Vergelijk per ruimte
de KNX-temperatuur, ingestelde analysegrenzen en weergegeven klimaatscores.
Controleer per buitenunit current/desired/proposed en de blokkeerreden. Test een
onbeschikbare bron en het herstel daarvan; Zonentra moet unknown melden in plaats
van een nieuwe modus bedenken. **Koppel de voorgestelde modi niet aan eigen
actuator-automations** als je deze versie read-only wilt testen. Dat geldt ook
voor de gesimuleerde acties uit 0.5: ze zijn bedoeld om te vergelijken met wat de
installatie werkelijk doet.

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

De suite omvat 92 tests. Pure kernfuncties worden zonder HomeAssistant-instance
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
  models.py                     pure topologie, centrale instellingen en validatie
  migration.py                  versiecompatibiliteit en behoud van ruimtebeleid
  observations.py               bronkwaliteit, leeftijd en eenheden
  demand.py                     ruimtesnapshots en klimaatvraag
  engine.py                     gewogen groepsarbitrage en verklaringen
  decision.py                   pure read-only simulator
  runtime.py                    HA-observatie en update-dispatch
  indoor.py                     binnenunitobservatie en afgeleide groepsmodus
  override.py                   Manual Override-detectie en command tracking
  control.py                    groepscoördinatie en gesimuleerde acties per unit
  sensor.py                     diagnostische sensoren
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
