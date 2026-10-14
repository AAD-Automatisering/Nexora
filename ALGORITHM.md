# Zonentra 0.9.0 — uitlegbare klimaatintelligentie

Dit document beschrijft vooral **read-only analyse**: een voorgestelde modus is geen
commando en verandert ook niet de intern bijgehouden actuele modus. De actieve
functies staan apart beschreven: de standregeling (0.7) en de ruimteregeling (0.9).

Sinds 0.6 worden de centrale configuratie en de losse ruimte-items vóór elke
berekening samengevoegd tot één gebouwmodel (`topology.assemble`). De algoritmes
hieronder zijn daardoor identiek voor het oude enkele item en de nieuwe opbouw.

## Gevalideerde bronnen en ruimtesnapshots

HA-states worden op de eventloop gekopieerd naar immutable `SourceState`-waarden.
De pure kern bouwt daaruit per ruimte een `ZoneSnapshot`: temperatuur, twee
grenzen, optionele vochtigheid/CO₂/buitentemperatuur, aanwezigheid, contacten en
IDs van gekoppelde HVAC-, vloerverwarmings- en zonweringsapparatuur.

Vooraf lost het model per ruimte de twee centrale keuzes op. Grenzen en grensentiteiten
komen samen uit het gebouw of uit de ruimte; hysterese en meetleeftijd vormen een
apart blok. Alleen actieve instellingen worden voor klimaatvraag gebruikt. Inactieve
lokale waarden zijn nooit een fallback bij ontbrekende centrale grensentiteiten.

Buitentemperatuur komt uitsluitend uit het gebouw, met een eigen maximale leeftijd.
Eén gevalideerde Reading wordt gedeeld door alle ruimtes. De bron wordt eenmaal
gevolgd en ingepland voor veroudering; buitenweer blijft optionele context.

`Reading.quality` onderscheidt:

| Quality | Betekenis |
|---|---|
| valid | Waarde en eenheid zijn geaccepteerd (bij update_based ook de rapportleeftijd) |
| missing | Bron niet geconfigureerd (`not_configured`) of niet aanwezig in HA (`source_missing`) |
| unknown | HA meldt expliciet unknown (`source_unknown`) |
| unavailable | HA meldt expliciet unavailable (`source_unavailable`) |
| stale | Alleen bij update_based: geen HA-rapport binnen de maximale updateleeftijd (`no_report_within_max_age`) |
| unreliable | Ongeldige/niet-interpreteerbare waarde: `not_numeric`, `not_finite`, `unsupported_unit`, `out_of_range`, `invalid_timestamp`, `untrusted_source` (restored/assumed), `unsupported_state` |

`unknown` en `unavailable` zijn samen de categorie “onbeschikbaar”; `unreliable`
is de categorie “ongeldig”. De bestaande namen blijven behouden zodat automations
op `sensor_health` en `source_health` niet breken. De reden-code staat in
`temperature_validation.reason` en in de diagnostiek.

Temperaturen met °C en °F worden naar Celsius genormaliseerd. Geen eenheid of een
onbekende eenheid wordt niet geraden. Temperatuurmetingen moeten tussen −50 en
65 °C liggen; analysegrenzen tussen 5 en 35 °C. NaN, infinity en niet-numerieke
waarden zijn ongeldig. Vochtigheid moet 0–100 % zijn en CO₂ 0–10.000 ppm. Deze
bereiken zijn plausibiliteitschecks, geen garantie van sensorcalibratie.

### Validatiestrategie (0.3.1)

Home Assistant biedt drie timestamps: `last_changed` (alleen bij een andere
state), `last_updated` (state of attributen veranderd) en `last_reported` (elke
keer dat de integratie de state schrijft, ook als niets veranderde). Veel bronnen
– KNX zonder `always_callback`, Modbus/MQTT met change-only publicatie, sommige
Shelly-configuraties – schrijven **niets** zolang de waarde gelijk blijft. Dan
blijven ook `last_reported` en `last_updated` staan. Ouderdom bewijst daar geen
storing.

| Strategie | Gebruik | Leeftijdcontrole |
|---|---|---|
| `state_based` (standaard) | Elke bron, ook change-only (KNX) | Geen. Een geldige, beschikbare HA-state is bruikbaar, hoe lang ongewijzigd ook |
| `update_based` (optioneel) | Alleen bronnen die **aantoonbaar periodiek rapporteren** | `stale` als `now − last_reported ≥ max_age_seconds` |

`update_based` gebruikt `last_reported`, nooit `last_changed`: een ongewijzigde
waarde met een recent rapport blijft geldig en herstelt direct bij het volgende
rapport. De strategie is per ruimte in te stellen, of centraal voor ruimtes die
de centrale meetparameters gebruiken. `update_based` vereist een maximale
updateleeftijd groter dan 0. Bij `state_based` wordt `max_age_seconds` bewaard
maar genegeerd. De strategie geldt voor temperatuur, vochtigheid en CO₂ van de
ruimte. Grensentiteiten (number/input_number) zijn instellingen en verouderen
nooit op leeftijd. Buitentemperatuur gebruikt ongewijzigd de eigen
`outdoor_max_age_seconds` (0 = geen leeftijdcontrole).

Beide strategieën blijven unknown/unavailable/restored/assumed-states, ongeldige
eenheden, NaN/infinity, waarden buiten bereik en ongeldige timestamps afkeuren.
Een toekomsttimestamp >5 seconden of een ontbrekende/tijdzoneloze timestamp is
onbetrouwbaar.

**Versheid wordt niet geclaimd zonder bewijs.** `freshness_verified` is alleen
`true` bij update_based met een rapport binnen de maximale leeftijd. Bij
state_based is het altijd `false`: de waarde is bruikbaar, maar niet bewezen
actueel. Ook een HA-rapport bewijst niet dat de fysieke sensor opnieuw gemeten
heeft; gecachte gatewaydata blijft een beperking van de bron.

Root cause 0.2/0.3.0: elke ruimtebron (ook grensentiteiten) werd na standaard
1800 s zonder `last_reported`-update `stale`, en een deadline-timer dwong dat af.
Een KNX-temperatuur die 44 minuten stabiel 20,7 °C bleef, viel daardoor uit de
vraagberekening (`insufficient_data`, `reliable_zones 0`) en herstelde pas bij
een nieuwe telegramwaarde.

Aanwezigheid: on → occupied, off → unoccupied, ontbrekend/ongeldig → unknown.
Contacten: on → open, off → closed. Voor statische binaire toestanden is er geen
leeftijdtimeout; unavailable/unknown/restored/assumed blijven wel ongeldig.
Afwezigheid, open ramen, CO₂, vochtigheid en buitenweer beïnvloeden in 0.3 de
klimaatvraag nog niet: dit is verzamelde context voor volgende modules.

Een gekoppelde grensentiteit gaat vóór de vaste UI-grens. Als die entiteit faalt,
volgt **geen stilzwijgende fallback** naar de vaste grens. Een eventueel nog
ontbrekende optionele sensor blokkeert temperatuurvraag niet.

## Aanwezigheid en beweging (0.8)

Vóór de klimaatvraag kiest `presence.py` per ruimte een band, naar het model van
Versatile Thermostat:

1. Aanwezigheid gebouw = `absent` → **afwezig**-band (`away_heating_limit` /
   `away_cooling_limit`, standaard 16 / 30 °C).
2. Anders: ruimte heeft een bewegingssensor en de beweging is `inactive` →
   **eco**-band (standaard 19 / 26 °C).
3. Anders → **comfort**: de normale grenzen (centraal of van de ruimte, inclusief
   grensentiteiten).

Beweging is `active` zodra de sensor minstens `motion_delay_seconds` (30 s) aan
staat, en blijft dat `motion_off_delay_minutes` (30 min) nadat hij uitging, mits
de beweging eerder bevestigd was. Korte passages tellen niet. Een onbekende of
onbeschikbare aanwezigheid of bewegingssensor geeft comfort; een sensorfout maakt
het dus nooit kouder of warmer dan normaal. De eco- en afwezig-band moeten net als
de comfortband ruimer zijn dan tweemaal de hysterese. De runtime plant een
herbeoordeling op het moment dat de detectie- of nalooptijd verstrijkt. De
bewegingsgeschiedenis staat alleen in het geheugen; na een herstart begint een
ruimte zonder recente beweging op eco.

## Temperatuurvraag per ruimte

Per ruimte: gemeten `T`, verwarmingsgrens `H`, koelgrens `C`, hysterese `h` en
weging `w`. Nieuwe UI-voorstellen: H=21 °C, C=24 °C, h=0,3 °C en w=1.
Dit zijn analysegrenzen; ze worden nooit naar VTherm of apparatuur geschreven.
Bestaande 0.1-configuraties krijgen geen stilzwijgende comfortgrenzen.

Voorwaarde: alle drie de benodigde readings zijn valid en `H + 2h < C`.
Anders: demand=unknown, scores=null, reden insufficient_data of invalid_limits.

1. Vorige vraag heating_demand en `T < H+h`: behoud heating_demand.
2. Vorige vraag cooling_demand en `T > C−h`: behoud cooling_demand.
3. Anders `T < H−h`: heating_demand.
4. Anders `T > C+h`: cooling_demand.
5. Anders neutral.

Bij een onbekende vorige vraag gelden de instapgrenzen uit stap 3/4. Een fout
reset de vorige vraag naar unknown; herstel begint weer met de instapgrenzen.

Scores (graden afwijking × configureerbare weging, geen kW of energie):

```text
heating_score = w × min(5, max(0, H−T))  bij heating_demand; anders 0
cooling_score = w × min(5, max(0, T−C))  bij cooling_demand; anders 0
```

Weegfactor 0,1–10, standaard 1. Afwijkingen zijn begrensd op 5 K per ruimte, zodat
één extreme meting niet onbeperkt domineert. Scores worden op vier decimalen
afgerond. Een door hysterese behouden vraag kan score 0 hebben als de grens al
bereikt is; vraagtoestand en huidige afwijking zijn verschillende grootheden.

## Buitenunitgroep: vraag, actuele modus en voorstel

Groepslidmaatschap komt uit de gekoppelde HVAC-apparatuur. Een groep telt iedere
ruimte **eenmaal**, ook bij meerdere binnenunits. Een zonegroep kan als standaard
voor haar HVAC-apparatuur dienen. Tegenstrijdige expliciete apparaat-/zonegroepen
zijn een configuratiefout. Vloerverwarming en zonwering tellen niet als HVAC-vraag.

Alle gekoppelde ruimtes moeten betrouwbare temperatuurvraag hebben en alle
HVAC-entiteiten moeten beschikbaar zijn. Een lege groep of onvolledige kritieke
data levert desired/proposed=unknown en blocked_reason=insufficient_data.
Beschikbare scores blijven zichtbaar met `reliable_zones` en `member_zones` zodat
gebruikers zien waarom ze nog geen volledig groepsbeeld hebben.

De actuele groepsmodus komt **alleen** uit een expliciet geselecteerde, betrouwbare
feedback-entiteit. Geldige waarden: heat, cool, off. Auto, heat_cool en ontbrekende,
verouderde of onbetrouwbare bronnen betekenen current_mode=unknown. Individuele
climate-setpoints of gewenste VTherm-modi bewijzen de fysieke buitenunitmodus niet.
Wanneer binnenunits binnen een beperkte groep expliciet zowel heat als cool
melden, blokkeert observed_group_conflict het plan; Zonentra corrigeert niets.

Bereken `S_heat=sum(heating_score)`, `S_cool=sum(cooling_score)` en `Δ=S_heat−S_cool`.
Standaard minimale score M=0,5; score-deadband D=0,5:

1. `max(S_heat,S_cool) < M`: desired=off, no_significant_demand.
2. `abs(Δ) < D`: behoud current heat/cool alleen als die richting score ≥ M heeft.
   Anders desired=unknown, blocked_reason=balanced_demand.
3. Anders: desired=heat bij Δ>0, anders cool.
4. Actuele modus unknown: proposed=unknown, blocked_reason=current_mode_unknown;
   gewenste richting blijft zichtbaar als deze berekenbaar is.
5. Desired verschilt van bekende current en minimuminterval is nog niet verstreken:
   proposed=current, blocked_reason=minimum_switch_interval, blocked_until=deadline.
6. Anders proposed=desired; mode_change_proposed is alleen true bij een werkelijk
   verschillend en volledig toegestaan **simulatievoorstel**.

De minimumtijd (standaard 900 seconden) geldt voor alle overgangen, ook vanaf/naar
off. Hij wordt gemeten vanaf de laatste **waargenomen** modusverandering of
betrouwbare heracquisitie. Een voorgestelde verandering reset de klok niet.
Op herstart en options-reload start een nieuwe conservatieve wachttijd. Dat kan
langer wachten betekenen, maar voorkomt dat restart een wachttijd omzeilt.
Er is geen persistente uitvoerstatus of hardwareplan om te herstellen.

### Voorbeeld uit de opdracht

A: 20 °C, H=21, C=24 → warmte, score 1. B: 23 °C → neutraal, score 0.
C: 24,8 °C → koeling, score 0,8. Met alle gewichten 1 is Δ=0,2, dus binnen de
standaarddeadband. Een bekende heat/cool-modus met voldoende vraag wordt behouden;
bij actuele off blijft het voorstel unknown wegens balanced_demand.
Met weging A=2 wordt Δ=1,2: desired=heat. Of proposed ook heat wordt, hangt af van
betrouwbare modusfeedback en de omschakelwachttijd. Zonder feedback blijft proposed
unknown. Dit kiest bewust stabiliteit boven een omschakeling bij een klein verschil.

## Binnenunits en afgeleide groepsmodus (0.4)

Binnenunits zijn de als `hvac`-apparatuur gekoppelde climate-entiteiten. De pure
module `indoor.py` interpreteert ze; de beslisengine (`engine.py`) is niet
gewijzigd en gebruikt deze interpretatie niet.

**Per binnenunit** wordt gelezen: beschikbaarheid, selected mode (entity state),
`hvac_action`, `current_temperature`, `temperature` (setpoint), `fan_mode` en
`last_updated`. Ontbrekende attributen worden niet geraden.

| Beschikbaarheid | Betekenis |
|---|---|
| available | Geldige state van een betrouwbare bron |
| missing | Entiteit bestaat niet (meer) in HA |
| unknown / unavailable | HA meldt dit expliciet |
| untrusted | `restored` of `assumed_state` |

| Selected mode | Classificatie |
|---|---|
| heat / cool | Verwarmen / koelen geselecteerd |
| off | Uit (geen bewijs dat de buitenunit uit is) |
| fan_only | Geen verwarmen of koelen geselecteerd |
| auto / heat_cool | Niet te classificeren zonder activiteit (`auto_mode_unclassified`) |
| dry | Apart; nooit automatisch gelijk aan cool (`dry_mode_selected`) |
| overig | `unsupported_mode_selected` |

`hvac_action`: heating/preheating/defrosting → heating; cooling → cooling;
drying → drying; idle/off/fan → inactief; ontbrekend → onbekend
(`hvac_action_missing`). Een selected mode die de gemelde activiteit niet kan
veroorzaken is een **mismatch** (bijv. off + heating, heat + cooling, fan_only +
cooling). heat + idle is normaal: ingesteld op verwarmen, nu niet actief.

**Per groep:**

1. *Selected consensus* (beschikbare units): heat én cool → `mixed`
   (`selected_heat_and_cool`); anders heat → `heat`, cool → `cool`; alleen
   off/fan_only → `off`; anders (auto/dry/onbekend) → `unknown`.
2. *Reported activity*: heating én cooling → `mixed`
   (`reported_heating_and_cooling`); anders heating, cooling, drying of
   `inactive`; zonder bruikbare `hvac_action` → `unknown`.
3. *Derived mode*: elk conflict → `mixed` met het conflict als reden. Anders
   consensus heat/cool (tenzij de activiteit tegenovergesteld is →
   `selected_heat_reported_cooling` / `selected_cool_reported_heating`),
   consensus off → `inactive` (`all_units_off` / `no_heat_or_cool_selected`),
   bij een ambigue modus alleen heat/cool als de activiteit dat meldt
   (`ambiguous_mode_heating_reported`), anders `unknown`. Geen units →
   `no_indoor_units`; geen beschikbare units → `no_available_indoor_units`.
   Een conflict wordt nooit opgelost door één unit voorrang te geven.
4. *Kwaliteit*: `completeness` = complete / partial (unit onbeschikbaar of
   modus onbruikbaar) / none. `quality` = consistent (alles bekend en eens) /
   selected_only (hvac_action ontbreekt) / partial / conflict / none.

Een off-unit naast een verwarmende unit is normaal en geen conflict.

**Vergelijking met de gewenste modus** (`observation_reason`, alleen diagnose):

| Situatie | Reden |
|---|---|
| Afgeleid gelijk aan gewenst (off ↔ inactive telt als gelijk) | observed_matches_desired |
| Gewenst heat/cool, units inactief | heat_requested_units_inactive / cool_requested_units_inactive |
| Gewenst heat, afgeleid cool (of omgekeerd) | mode_mismatch_observed |
| Gewenst off, units verwarmen/koelen | units_active_without_demand |
| Afgeleid mixed / unknown | indoor_units_conflict / indoor_observation_unknown |
| Gewenst unknown | desired_mode_unknown |
| Geen binnenunits | no_indoor_units |

**Veiligheidsregel.** `physical_mode` is uitsluitend de bestaande `current_mode`
uit de expliciet ingestelde modus-feedback van de groep. De afgeleide modus vult
die nooit in, verandert `desired_mode`, scores of `proposed_mode` niet, en kan
`current_mode_unknown` niet opheffen of een omschakeling vrijgeven.

## Gesimuleerde regelstrategie (0.5)

**Alles in dit hoofdstuk is simulatie.** De pure modules `override.py` en
`control.py` importeren geen Home Assistant en roepen geen services aan. Elk
resultaat draagt `simulation: true`; stappen worden nooit als uitgevoerd of
bevestigd gerapporteerd. De Decision Engine (0.2–0.4) is ongewijzigd.

### Niveau A — leidende groepsmodus

| Decision Engine | Groepsmodus |
|---|---|
| desired heat / cool | heat / cool |
| desired off (geen significante vraag) | neutral |
| score-deadband (gebalanceerd) | huidige gecoördineerde modus als die zelf ≥ minimale vraagscore heeft, anders neutral |
| observed_group_conflict (units al in heat én cool) | de complete zonevraag beslist met dezelfde drempels (minimale score, deadband), zodat afwijkende units gecorrigeerd kunnen worden |
| insufficient_data, onbeschikbare units, ontbrekende sensoren | unknown → alle nieuwe acties geblokkeerd |

De groepsmodus is leidend voor iedere binnenunit in de groep, ook tijdens een
handmatige override. Bij neutral kiest Zonentra nooit zelf heat of cool. Een
"laatst bekende modus als voorkeur" bij neutral is bewust niet geïmplementeerd.

### Niveau B — actie per binnenunit

Volgorde (de eerste regel die geldt beslist):

1. Unit onbeschikbaar/ontbrekend/onbetrouwbaar → `blocked` (`indoor_unit_unavailable`).
2. Groepsmodus unknown → `blocked` (`group_mode_unknown`).
3. Groepsomschakeling bezig → zie state machine; een override omzeilt die niet.
4. Manual override actief:
   - groep heat/cool: compatibele modus → `hold` (`manual_override`), anders
     `correct_mode` naar de groepsmodus (`manual_override_mode_corrected`);
   - groep neutral: als geen andere unit in de tegengestelde modus draait →
     `hold` (`manual_override_neutral`); `auto` volgt draaiende units of wordt
     `blocked` (`mode_undetermined`); tegengestelde draaiende units → `blocked`
     (`group_conflict`), nooit willekeurig een kant kiezen.
5. Zonevraag unknown (sensorfout) → `blocked` (`zone_demand_unknown`).
6. Zonevraag gelijk aan groepsmodus → `turn_on_heat` / `turn_on_cool`, `hold`
   (`following_group_mode`) of `correct_mode`.
7. Anders gewenst `off`: `no_zone_demand`, `group_mode_neutral`,
   `zone_demand_conflicts_group_mode` of `override_expired` → `turn_off` of `hold`.

Compatibele modi: bij heat → heat, fan_only; bij cool → cool, dry, fan_only.
`desired_mode` is de eindtoestand, `action` alleen de eerstvolgende stap en
`steps` de volledige reeks (bijv. `turn_off → wait_changeover → turn_on_cool`).

### Anti-pendel

| Instelling | Standaard | Soort | Regel |
|---|---|---|---|
| `min_on_seconds` | 600 s | comfort | geen `turn_off` binnen deze tijd na inschakelen |
| `min_off_seconds` | 180 s | veiligheid | geen `turn_on` binnen deze tijd na uitschakelen |
| `changeover_wait_seconds` | 300 s | veiligheid | wachttijd tussen stoppen en de tegengestelde modus |
| groep `min_switch_seconds` | 900 s | comfort | bestaande parameter, hergebruikt: minimale tijd per groepsmodus |

De tijd sinds de laatste overgang is HA `last_changed` van de climate-state; na een
herstart begint die opnieuw (conservatief). Een geblokkeerde actie toont
`blocked_until`, en de runtime plant daarop een herbeoordeling. De standaard
veiligheidswaarden zijn **niet geverifieerd** met Mitsubishi-documentatie.

### Groepsomschakeling (state machine)

| Fase | Wanneer |
|---|---|
| idle / completed | geen omschakeling nodig (completed blijft staan na de laatste omschakeling) |
| preparing | omschakeling gewenst, minimale groepsmodusduur nog niet verstreken (`waiting_until`) |
| blocked | groepsmodus unknown, units onbeschikbaar of harde conflicten |
| stopping | units in een incompatibele modus draaien nog → gepland `turn_off` |
| waiting | niets meer te stoppen; veiligheidswachttijd vanaf het eerste moment zonder draaiende units |
| applying | units met vraag of override staan nog niet in de nieuwe modus |
| verifying | units staan in de nieuwe modus, afgeleide groepsmodus nog niet consistent |
| failed | geselecteerde modus en gemelde activiteit spreken elkaar tegen |

De fase volgt **uitsluitend waarnemingen**: zonder commando's blijft een
omschakeling in read-only bijvoorbeeld in `stopping` staan zolang units in de oude
modus draaien. `switch_allowed_in_simulation` zegt of de voorwaarden in de
simulatie vervuld zijn; `active_switch_permitted` is in 0.5 altijd `false`
(blockers `read_only_simulation` en, zonder fysieke modusfeedback,
`current_mode_unknown`). Voor toekomstige coördinatie zonder buitenunitfeedback
zijn de voorwaarden: alle units beschikbaar, geen harde conflicten, verlopen
anti-pendeltijden, en een geverifieerde (selected én reported) eindtoestand.

### Manual override

Bron: de state-events van de gekoppelde climate-entiteit. Classificatie van één
`state_changed`-event:

| Overgang | Classificatie | Override |
|---|---|---|
| off → heat/cool/dry/fan_only/auto/heat_cool | manual_on | start (tenzij uitgeschakeld) |
| actief → off | manual_off | eindigt |
| actief → andere actieve modus | mode_change | ongewijzigd (timer niet verlengd) |
| zelfde state, andere attributen | attribute_update | ongewijzigd |
| unknown/unavailable → actief | from_unavailable | nooit |
| entiteit verschijnt / HA-start / setup | initial / geen event | nooit |
| restored of assumed_state | untrusted | nooit |
| overeenkomend met een Zonentra-commando | zonentra_initiated | nooit |

Same-value-rapporten (`state_reported`) en timers zijn geen overgangen.
**Beperking:** HA-events bewijzen de herkomst niet. Een externe automatisering
die een unit aanzet is niet te onderscheiden van de roomcontroller en start dus
ook een override.

`CommandTracker` (voor toekomstige aansturing) registreert per entiteit de
verwachte state met een begrensde bevestigingsperiode (60 s). Alleen een
overgang naar precies die state binnen die periode telt als Zonentra-initiatief;
daarna is elke overgang weer extern. Er is geen open tijdsvenster dat echte
gebruikersacties onderdrukt. In 0.5 blijft de tracker leeg.

Timer: `expires_at = start + manual_override_duration_minutes` (standaard 30,
5–120). Alleen een nieuwe off→aan-overgang start een nieuwe override; updates,
moduscorrecties en rapporten verlengen niets. De runtime plant een herbeoordeling
op `expires_at`, zodat de override ook zonder nieuwe events afloopt. Daarna geldt
de normale regeling (`override_expired` → `turn_off` zonder vraag). Tijd komt uit
één expliciete bron (`dt_util.utcnow` in de runtime, `now` als parameter in de
pure kern), waardoor alles deterministisch testbaar is.

**Herstart:** overrides staan alleen in het geheugen en overleven een herstart
niet. Een verlopen override kan dus nooit terugkomen en een herstart start nooit
een override. Een unit die na een herstart aan staat zonder vraag krijgt de normale
`turn_off`-intentie (met minimale aan-tijd vanaf de herstart).

## Actieve standregeling (0.7)

Dit was de eerste actieve functie. `executor.plan_mode_commands()` is puur; de runtime
voert de commando's uit via `climate.set_hvac_mode` en `climate.turn_off`.

**Doelmodus** = de leidende groepsmodus uit de coördinator (heat/cool). Bij neutral of
unknown wordt niets gestuurd en blijft de laatst gezette stand (`PresetMemory`).

**Wissel** (doel ≠ laatst gezette stand): alleen als sinds de vorige wissel de
bestaande groepsparameter `min_switch_seconds` (standaard 900 s) verstreken is.
Dan per beschikbare unit:
- uit → `set_hvac_mode(doel)`, na 3 s `turn_off` (`preset_pulse`); de uit-puls wordt
  overgeslagen als de unit intussen een andere state heeft;
- aan in een niet-compatibele modus → `set_hvac_mode(doel)` (`switch_running_unit`);
- aan in een compatibele modus (heat: heat, fan_only; cool: cool, dry, fan_only) → niets.

**In sync:** een draaiende unit in een niet-compatibele modus wordt na 30 s
gecorrigeerd (`correct_running_unit`), per unit hooguit eens per 120 s. De runtime
plant een herbeoordeling op het moment dat een correctie mogelijk wordt.

**Veiligheid:** elk commando wordt vooraf in de CommandTracker geregistreerd
(verwachte state, 60 s), zodat de eigen overgang geen Manual Override start.
Fouten worden gelogd (`failed: …`) en breken de runtime niet. Zonder climate-service
wordt niets gestuurd en ook niets als "gezet" onthouden. De schakelaar per groep
(RestoreEntity, standaard aan) stopt alle commando's direct, inclusief openstaande
uit-pulsen; tot hij na een herstart is hersteld, wordt niets gestuurd. De laatst
gezette stand staat in HA-opslag en overleeft herstarts.

**Herkomst van overgangen** (Manual Override): de HA-context van het
`state_changed`-event. Een gebruiker (`user_id`) of een kale context (KNX-roomcontroller)
→ `manual_on`; een context met `parent_id` (automation/script) → `automation_on`,
geen override. Dit is een sterke aanwijzing, geen bewijs.

## Ruimtethermostaat en ruimteregeling (0.9)

`thermostat.py` is puur; de runtime bewaart de thermostaat per ruimte in HA-opslag
(`zonentra.<centrale>.thermostats`) en houdt een kopie in `hass.data`, zodat een
herlaad van de centrale configuratie een net gemaakte wijziging niet verliest.

**Band.** `active_band(preset, bezetting)`: bij een afwezig gebouw altijd `away`;
preset `activity` volgt de bezetting uit 0.8; anders de vaste preset. De
comfortband is de eigen band van de thermostaat als die is ingesteld, anders de
geconfigureerde grenzen (`demand.comfort_limits`). Eco en afwezig blijven centraal.
Een eigen band moet voldoen aan `verwarmen + 2·hysterese < koelen`, beide 5–35 °C.

**Thermostaatmodus** (standaard HA-modi, `room_demand`): `heat_cool` laat de vraag
ongemoeid; `heat` maakt koelvraag `neutral` (`thermostat_heat_only`), `cool` maakt
verwarmingsvraag `neutral` (`thermostat_cool_only`), `off`, `dry` en `fan_only` maken
alle vraag `neutral` (`thermostat_off`, `thermostat_dry`, `thermostat_fan_only`).
De thermostaat biedt `dry`, `fan_only` en ventilatorstanden alleen aan als alle
binnenunits van de ruimte ze kennen, en noemt `heat_cool` `auto` als de units dat
doen (opgeslagen blijft `heat_cool`). Met ruimteregeling zet `plan_room_mode` de
units eenmaal per thermostaatwijziging in `dry`/`fan_only` (na `min_off_seconds`,
niet tijdens een Manual Override; `dry` alleen als de groep mag koelen, anders gaat
een door Zonentra drogende unit uit), en `plan_fan` geeft de ventilatorstand
eenmaal per wijziging door aan draaiende units. De groep weegt daarna zoals altijd; een modus dwingt nooit de
buitenunit. Eén doeltemperatuur (`heat`/`cool`) zet de verwarmings- of koelgrens;
de andere grens blijft staan, of schuift mee als de band anders ongeldig wordt
(`single_target`).

**Aan/uit (alleen met Ruimteregeling aan).** De runtime voert de bestaande actie per
binnenunit uit (0.5): `turn_on_heat`/`turn_on_cool` → `set_hvac_mode`,
`turn_off` → `climate.turn_off`. `correct_mode` blijft aan de standregeling,
`hold`/`blocked` sturen niets. Inschakelen gebeurt alleen in een *veilige* modus:
met actieve standregeling de klaargezette stand van de groep; zonder standregeling
de stand van de units die al draaien (heat, of cool/dry), allebei = conflict = niets,
geen enkele = vrij. Zolang een eigen commando nog niet is bevestigd
(CommandTracker), of de standregeling in dezelfde ronde of met een openstaande
uit-puls met de unit bezig is, wacht de ruimteregeling.

Een openstaande uit-puls van de standregeling wordt overgeslagen
(`skipped_room_demand`) als de ruimte geregeld wordt en de unit in die stand nodig
heeft (`desired_mode` van de actie = doelstand).

**Zelfregulerend setpoint** (`plan_setpoint`) voor een draaiende unit zonder actieve
override, met geldige ruimtetemperatuur en een `temperature`-attribuut:

- verwarmen: basis = verwarmingsgrens + hysterese,
  setpoint = basis + clamp(basis − T_ruimte, −max, +max);
- koelen: basis = koelgrens − hysterese,
  setpoint = basis − clamp(T_ruimte − basis, −max, +max);
- grenzen van de actieve band; afgerond op `target_temp_step` (standaard 0,5) en
  begrensd op `min_temp`/`max_temp` van de unit (standaard 16–30 °C);
- `max` = `setpoint_max_offset` (standaard 2 °C); versturen alleen bij een verschil
  van minstens een halve stap en hooguit eens per `setpoint_interval_seconds`
  (standaard 300 s); de runtime plant een herbeoordeling na de wachttijd.

De versterking is bewust 1 en zonder integratie: de unit regelt zelf, Zonentra
verschuift alleen zijn doel zodat de ruimtesensor in plaats van de unitsensor telt.

**Mensen gaan voor.** In een geregelde ruimte start naast `manual_on` ook
`manual_off` (unit blijft uit, `manual_override_off`) en `manual_setpoint` een
Manual Override. Een setpointwijziging is `zonentra_setpoint` als ze het verwachte
eigen setpoint bevestigt, `automation_setpoint` met een `parent_id`-context, en
`setpoint_after_command` binnen 60 s na een eigen commando (een integratie kan bij
inschakelen zijn eigen setpoint terugzetten). Alleen de rest is `manual_setpoint`.

## Events en herbeoordeling

Bronveranderingen gebruiken `async_track_state_change_event`. Voor rapporten met
ongewijzigde waarde is er een gefilterde `EVENT_STATE_REPORTED`-listener, zoals de
actuele HA-API voorschrijft. De runtime plant slechts één timer naar de eerstvolgende
sensorvervaldatum of geblokkeerde omschakeldeadline. Er is geen periodieke polling.
Binnenunits zijn al gevolgde apparatuurentiteiten: een `hvac_action`-wijziging
is een attribuutwijziging en komt via hetzelfde state_changed-event binnen.
Override-afloop, anti-pendelblokkades en wachttijden van de omschakeling worden
als deadlines in dezelfde ene timer meegenomen.
Bij unload worden zowel bronlisteners als de timer verwijderd.

De beslisengine importeert geen Home Assistant en heeft geen uitvoerinterface.
Elke fysieke apparatuurvermelding blijft daarnaast een hold-beslissing behouden
in de bestaande Status-sensor, ook als de nieuwe groepssensor een mode voorstelt.
