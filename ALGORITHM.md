# Zonentra 0.4.0 — uitlegbare klimaatintelligentie

Alles in dit document betreft **read-only analyse**. Een voorgestelde modus is
geen commando, en verandert ook niet de intern bijgehouden actuele modus.

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

## Events en herbeoordeling

Bronveranderingen gebruiken `async_track_state_change_event`. Voor rapporten met
ongewijzigde waarde is er een gefilterde `EVENT_STATE_REPORTED`-listener, zoals de
actuele HA-API voorschrijft. De runtime plant slechts één timer naar de eerstvolgende
sensorvervaldatum of geblokkeerde omschakeldeadline. Er is geen periodieke polling.
Binnenunits zijn al gevolgde apparatuurentiteiten: een `hvac_action`-wijziging
is een attribuutwijziging en komt via hetzelfde state_changed-event binnen.
Bij unload worden zowel bronlisteners als de timer verwijderd.

De beslisengine importeert geen Home Assistant en heeft geen uitvoerinterface.
Elke fysieke apparatuurvermelding blijft daarnaast een hold-beslissing behouden
in de bestaande Status-sensor, ook als de nieuwe groepssensor een mode voorstelt.
