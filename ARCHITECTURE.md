# Zonentra — architectuur

Status: versie 0.6.0, VTherm-achtige opbouw (centrale configuratie + ruimte-items), gesimuleerde regelstrategie en Manual Override, binnenunitobservatie, sensorvalidatie, centrale configuratie en Building Intelligence in read-only simulatie, 12 oktober 2026.

## Projectnaam en integratie-identiteit

Vanaf versie 0.1.2 heet het project **Zonentra**. De Home Assistant-domain is
`zonentra` en alle runtime-bestanden staan in `custom_components/zonentra`.
Config-entry unique ID, apparaatidentifiers en interne signalen gebruiken deze
domain. Omdat het project in de testfase zit, is er geen compatibiliteitslaag of
migratie van eerdere Nexora-testconfiguraties. Installeer en configureer deze integratie
opnieuw; de README beschrijft de overgang.

## Scope en belangrijkste keuzes

**Eén Home Assistant-installatie = één Zonentra = één gebouw.** De Config Flow,
vaste unique ID en `single_config_entry` in het manifest begrenzen dit expliciet.
Meerdere ruimtes en fysieke installaties worden binnen dat gebouw gemodelleerd.
Er is geen multi-building beheerlaag. Het entry-ID vormt alleen een stabiele
namespace voor runtime en diagnostische entiteiten.

Zonentra coördineert uiteindelijk comfort, energie en installatiebeperkingen, maar
versie 0.3 observeert bestaande Home Assistant-entiteiten en berekent vraag en
groepsvoorstellen. De gepubliceerde entiteiten zijn uitsluitend diagnostische sensoren. Er zijn geen actuatorservices,
climate-platform, serviceregistraties of serviceaanroepen. De vloerverwarmingsgrens
van 16 °C wordt nergens als verstelbaar setpoint opgeslagen of geschreven.
Lokale KNX-veiligheid en bestaande VTherm/KNX/Shelly-automations blijven functioneren.

### Besluit A — pure kern en dunne HA-adapter

`models.py`, `observations.py`, `demand.py`, `engine.py` en de bestaande hold-
simulator `decision.py` importeren geen Home Assistant. `runtime.py`
leest state en publiceert updates, `config_flow.py` beheert de UI, `sensor.py` toont
status. Runtime staat in de getypeerde `ConfigEntry.runtime_data`.

Alternatief: tien managers met eigen eventbussen en onderlinge afhankelijkheden.
Dat levert voor het fundament veel levenscyclus- en synchronisatiewerk op. Daarom
zijn Building, Zone en Equipment nu datamodellen; er komen pas zelfstandige managers
als ze eigen gedrag nodig hebben. Geen lege implementaties voor toekomstige modules.

### Besluit B — voorstellen centraal arbitreren

Een toekomstige module mag alleen een voorstel indienen. Eén Decision Engine
beoordeelt alle voorstellen uit dezelfde snapshot en maakt één plan. Eén toekomstige
uitvoerlaag bezit de bevoegdheid om HA-services aan te roepen. Ook versie 0.3 bevat die laag
niet. Meerdere apparaten met hetzelfde fysieke entity-ID worden afgewezen.
De fysieke Mitsubishi-climate wordt als apparatuur aan een ruimte gekoppeld.
Er is geen aparte ruimteregelaarkoppeling of VTherm-adapter. Klimaatvraag gebruikt
de externe ruimtetemperatuur en effectieve analysegrenzen.

Alternatief: elke module rechtstreeks climate/cover/fan laten bedienen. Dat kan
tegengestelde acties, KNX-verkeer en onverklaarbare prioriteiten veroorzaken.

### Besluit C — UI-opties als één topologietransactie

`ConfigEntry.data` bevat de gebouwnaam; `options` bevat de aanpasbare lokale
indeling. De Options Flow bewerkt een diepe kopie, valideert verwijzingen bij elke
bewerking en slaat uitsluitend bij Opslaan op. `OptionsFlowWithReload` vervangt
listeners en runtime na een wijziging. Sluiten annuleert de transactie.

Zones, buitenunitgroepen en apparatuur krijgen automatisch een stabiel intern
UUID (hexnotatie). De UI vraagt alleen om namen en koppelingen; namen mogen
veranderen. Bestaande, eerder handmatig gekozen IDs blijven ongewijzigd. Verwijderen van een nog gebruikte ruimte of groep is
geblokkeerd. Optionele koppelingen zijn te wissen. Nieuwe entiteiten moeten in de
HA state machine of registry bestaan; reeds gekoppelde offline entiteiten blijven
bewerkbaar. Eigen Zonentra-entiteiten kunnen geen input worden.

Alternatief: Config Subentries per ruimte. De officiële HA-architectuur ondersteunt
ze, maar onderlinge groep-/apparatuurverwijzingen vragen dan extra beheer over
verschillende transacties. Een compact options-document is voldoende voor circa
tien ruimtes. Bij sterk groeiende topologie kan een versioned migratie dit aanpassen.
Geen YAML, custom frontend of ongedocumenteerde storage-mutaties.

### Besluit D — gebeurtenissen, geen polling

`async_track_state_change_event` volgt alleen gekoppelde entity-IDs. De initiële
snapshot wordt bij setup gelezen; nieuwe of herstelde bronnen worden via events
opgepikt. `async_dispatcher_send/connect` verbindt runtime met de sensor. De sensor
heeft `should_poll=False`. `async_on_unload` en entity remove-callbacks ruimen
subscriptions op. Geen netwerkclient of cloud nodig.

Alternatief: periodieke DataUpdateCoordinator. Er is geen extern endpoint om te
pollen, dus dit voegt geen waarde toe. Tijdsafhankelijke beslissingen gebruiken één expliciete timer naar de eerstvolgende
meetvervaldatum of omschakeldeadline. Een gefilterde state_reported-listener neemt
ook nieuwe rapporten met dezelfde waarde mee; last_changed wordt niet als freshness
gebruikt. Sinds 0.3.1 krijgen alleen bronnen met `update_based`-validatie een
vervaldatum; standaard (`state_based`) keurt de timer geen geldige waarde af. Alle subscriptions en timers worden opgeruimd bij unload.

## Config entries (0.6)

Zoals Versatile Thermostat bestaat Zonentra uit één **centrale configuratie**
(`entry_type: central`, unique ID `central`) en een **config entry per ruimte**
(`entry_type: zone`). De centrale entry bewaart `building` (instellingen) en
`groups`. Een ruimte bewaart haar eigen zone-record plus `indoor_units`,
`floor_heating_entities`, `shading_entities` en `ventilation_entities`.

`topology.assemble()` (puur) voegt beide samen tot het bestaande topologieformaat;
`build_model()` en de hele rekenkern zijn ongewijzigd. Apparatuur-ID's volgen uit
de gekoppelde entiteit (`hvac_<object_id>`), dus ze zijn stabiel en uniek, en een
entiteit hoort bij precies één ruimte.

Alleen de centrale entry bezit een `BuildingRuntime` met listeners en de timer.
Een ruimte-entry heeft geen eigen logica: haar sensoren lezen de centrale runtime
via een provider en luisteren naar het vaste signaal `zonentra_<central_id>_updated`,
zodat ze een herlaadbeurt van de centrale entry overleven. Een nieuwe, gewijzigde
of verwijderde ruimte laat de centrale entry opnieuw opbouwen. Een ruimte zonder
centrale configuratie geeft een setupfout; is die nog niet geladen, dan probeert HA
het later opnieuw (`ConfigEntryNotReady`).

De pre-0.6-entry zonder `entry_type` ("legacy") werkt ongewijzigd door, met zijn
oude opties-flow en unique ID's. Hij is verouderd en meldt een reparatie-issue.

## Datamodellen (geïmplementeerd)

| Model | Belangrijkste velden | Invariant |
| --- | --- | --- |
| Building | id, name, settings, zones, groups, equipment | Eén gebouw per installatie |
| BuildingSettings | buitentemperatuurbron/leeftijd, centrale grenzen/entiteiten, hysterese, meetleeftijd | Eén gedeelde bron; geen verzonnen migratiegrenzen |
| Zone | id, name, bronkoppelingen, analysegrenzen, weight, hysteresis, max_age_seconds, group_id | Geen implicit setpoint; optionele context blokkeert niet |
| EquipmentGroup | id, name, mode_entity, single_hvac_mode, min_switch_seconds, scoreparameters | Eén gewogen voorstel; actuele modus niet raden |
| Equipment | id, name, kind, entity_id, zone_id, group_id | Eén zone per apparaat; groep alleen bij HVAC; fysieke entiteit uniek |
| Observation | state, quality | missing, unknown, unavailable of observed |
| Decision | equipment_id, action, reason | Fase 1: action uitsluitend hold |

Dataclasses voor de topologie zijn immutable en verzamelingen zijn tuples. Nieuwe IDs zijn automatisch gegenereerde UUIDs in hexnotatie. Bestaande IDs blijven
geldig en uniek per categorie: kleine letters/cijfers/`_`/`-` (maximaal 64 tekens).
Groepslidmaatschap loopt via apparatuur, zodat meerdere binnenunits per ruimte en
per buitenunit mogelijk zijn. Niet-HVAC-apparatuur kan zonder groep geregistreerd
worden als floor_heating, shading, ventilation of other. Equipment is een logisch
model voor een bestaande HA-entiteit, geen nieuw fysiek apparaat in de HA-registry.

De bestaande `Observation`/`Decision` blijven beschikbaar voor de 0.1-compatible
Status-sensor met fysieke hold-beslissingen. De nieuwe, pure analysemodellen zijn:

| Model | Rol |
|---|---|
| SourceState | Gekopieerde HA-state, eenheid, last_reported, last_changed (diagnostisch), trustworthy-vlag |
| Reading | Gevalideerde waarde met valid/missing/unknown/unavailable/stale/unreliable, reden-code, strategie (state_based/update_based) en freshness_verified |
| ZoneSnapshot | Temperatuur, analysegrenzen, context en gekoppelde equipment-IDs |
| ZoneDemand | Hysteretische vraag, twee gewogen scores, kwaliteit en reden |
| GroupMemory | Alleen laatst geobserveerde betrouwbare modus en waarnemingstijd |
| GroupDecision | current/desired/proposed, geaggregeerde scores, redenen en deadline |
| ClimateAttributes | Gekopieerde hvac_action, temperaturen, fan_mode en last_updated van een climate-entiteit |
| IndoorUnitObservation | Beschikbaarheid, selected mode, reported action, kwaliteit en mismatch per binnenunit |
| GroupModeObservation | Consensus, activiteit, afgeleide modus, conflicten, volledigheid, kwaliteit en reden per groep |
| ManualOverride | Start, absolute eindtijd en startmodus per binnenunit (alleen in geheugen) |
| PendingCommand / CommandTracker | Verwachte state van een Zonentra-commando met begrensde bevestigingsperiode (ontwerp voor actieve aansturing; leeg in 0.5) |
| CoordinationMemory | Gecoördineerde groepsmodus, sinds wanneer, en voortgang van een omschakeling |
| GroupCoordination | Leidende groepsmodus, omschakelfase, blockers, geplande acties; `simulation=True`, `active_switch_permitted=False` |
| UnitIntent | Waargenomen en gewenste modus, eerstvolgende actie, stappen, reden, blokkade, override en resterende tijd |

`control.plan()` is de Control Intent Engine: een pure functie van klimaatvraag,
groepsbesluit, binnenunitobservaties, overrides, tijdsparameters en `now`. Er is
geen uitvoeradapter; een toekomstige adapter zou intents vertalen naar services en
elk commando eerst in de CommandTracker registreren.

De runtime verzamelt één snapshot op één UTC-tijdstip. `collect_zone` bouwt pure
snapshots, `calculate_demand` berekent behoeften, `evaluate`/`decide_group`
arbitreren per installatiegroep. Reden-codes zitten direct in de resultaten;
sensor.py vertaalt presentatie, diagnostics.py maakt een geredigeerde export.
Er is geen uitvoeradapter. Extra context is al configureerbaar en gekoppelde
vloerverwarming/zonwering zit in de snapshot, maar krijgt geen regelgedrag.

Zie [ALGORITHM.md](ALGORITHM.md) voor het volledige geïmplementeerde algoritme.
Harde randvoorwaarden gaan vóór scoreafwegingen: alle kritieke groepsdata moeten
betrouwbaar zijn, actuele modus mag niet geraden worden en omschakelwachttijden
worden nooit door een voorstel zelf gereset. Optionele context blokkeert niet.
Herstart/reload begint met een conservatieve wachttijd; er wordt geen uitvoerplan
of hypothetische modus opgeslagen/hersteld.

### Centrale configuratie en compatibiliteit

Config Flow VERSION is 3. `options.building` bevat centrale instellingen;
`use_building_limits` en `use_building_parameters` bepalen onafhankelijk welke
blokken een ruimte overneemt. `effective_zone` bouwt een immutable runtimeprofiel;
de opgeslagen lokale waarden blijven beschikbaar wanneer de gebruiker terugschakelt.
Er is geen fallback naar inactieve lokale waarden bij ontbrekende centrale data.

| Niveau | Instellingen | Reden |
|---|---|---|
| Gebouw | Buitenbron + eigen leeftijd; standaard grenzen/entiteiten, hysterese en meetleeftijd | Gedeelde weerbron en herbruikbaar ruimtebeleid |
| Ruimte | Optioneel eigen grenzen/parameters; temperatuur, bezetting, vocht, CO₂, contacten, gewicht | Lokale metingen en comfortafwijkingen |
| Buitenunitgroep | Modusfeedback, feedbackleeftijd, minimuminterval, scoregrens en deadband | Eigenschappen van de gedeelde fysieke installatie |
| Apparatuur | Fysieke entiteit, ruimte en groep | Expliciete topologie en eigenaarschap |

De v1/v2→v3-migratie behoudt bestaande eigen grenzen en meetparameters, zonder ze
stilzwijgend door een centraal profiel te vervangen. Oude ongeconfigureerde grenzen
blijven None. Eén unieke oude buitenbron wordt centraal gezet; verschillende oude
bronnen worden kandidaten totdat de gebruiker er één selecteert. De bronleeftijd
wordt de kleinste positieve ingestelde leeftijd (0 als alle checks uit stonden).
De oude `controller_entity` wordt verwijderd en niet meer gevolgd; ontbrekende
VTherm-states beïnvloeden de gebouwstatus niet. De normalisatie is idempotent en verandert de invoer niet. IDs, configuratie-entry,
apparaatkoppelingen en diagnostische sensor-identiteiten blijven behouden.

Nieuwe gebouwen krijgen expliciete UI-beginwaarden; nieuwe ruimtes nemen centraal
over. De bestaande klimaatanalyse werkt op de effectieve profielen. Buitentemperatuur
wordt eenmaal per evaluatie gevalideerd en als dezelfde Reading gedeeld met alle
ruimtes; de runtime plant ook maar één vervaldeadline voor deze bron.

Nieuw toegevoegde zones en groepen krijgen automatisch diagnostische entiteiten.
Verwijderde zones/groepen verliezen uitsluitend hun eigen diagnostische registry-
records; fysieke bronentiteiten blijven bestaan. Een naamwijziging houdt hetzelfde
ID en dezelfde sensor. Bronnen die tot Zonentra zelf behoren zijn afgewezen bij
configuratie én setup om terugkoppeling te voorkomen.

## Modulegrenzen (ontwerp voor volgende fases)

De onderstaande interfaces zijn **Zonentra-ontwerpcontracten**, geen bestaande HA-API's
of al geïmplementeerde managers:

| Onderdeel | Input | Output / verantwoordelijkheid |
| --- | --- | --- |
| Building Manager | Topologie, planning, snapshots | Coördinatie van één gebouw en evaluatierondes |
| Zone Manager | Sensoren, gewenste comfortband, bezetting | ZoneSnapshot met kwaliteit en wensen |
| Equipment Manager | Topologie, gemelde modi, tijden, capabilities | EquipmentSnapshot en harde beperkingen |
| Climate Module | ZoneSnapshot | Warmte-/koelvoorstellen |
| Shading Module | Zon, weer, gevel, lokale veiligheid | Schaduwvoorstel, invloed op koelvraag |
| Ventilation Module | CO₂, bezetting, beschikbaarheid | Ventilatievoorstel; luchtkwaliteit vóór kosten |
| Occupancy Module | Alarm, mmWave, timers | occupied / unoccupied / unknown per niveau |
| Energy Module | P1, PV, meters, tarieven | Energiecontext met measured/estimated/unknown provenance |
| Decision Engine | Alle voorstellen, harde beperkingen | Eén verklaarbaar plan met afwijzingen |
| Diagnostics | Snapshot, plan, redenen | Status, uitleg, privacybewuste export |

Een module krijgt een immutable snapshot en levert `Proposal`-waarden (module,
resource, intent, prioriteit, reden, geldig-tot); geen `hass` of uitvoeradapter.
`evaluate(snapshot, now) -> proposals` wordt de pure testbare grens. De Engine levert
`DecisionPlan` met gekozen én afgewezen voorstellen en reason codes. Dependencies blijven één richting op: HA-adapter → kern.

## Prioriteiten en conflictpreventie voor toekomstige actieve regeling

1. Harde veiligheids- en installatiebeperkingen worden altijd toegepast. Lokale
   KNX-windveiligheid blijft leidend; Zonentra mag die niet uitschakelen. De 16 °C-
   ondergrens van gasvloerverwarming is beschermd en niet automatisch te wijzigen.
2. Handmatige override blokkeert automatisch beheer van de betrokken resource.
   Een override mag geen gedeelde buitenunitbeperking omzeilen. Bij zo'n conflict
   worden automatische acties geschorst en wordt de beperking uitgelegd.
3. Beschermende comfort-/luchtkwaliteitsgrenzen, dan normale comfortvraag.
4. Planning en aanwezigheid, vervolgens energie- en kostenoptimalisatie.

Voorstellen worden per fysieke installatie en per gedeelde buitenunitgroep
gegroepeerd. Een groep krijgt maximaal één heat/cool-modus per evaluatie. Bij gelijk
gewogen tegengestelde vraag blijft een geldige huidige modus staan; anders wordt
hold gekozen. Zoneweigeringen blijven zichtbaar. Modushysterese, minimumlooptijd,
minimum-uitlooptijd en omschakelvertraging zijn harde poorten, geen soft scores.
Fase 2 moet expliciet een gevalideerde off/wachttijd/nieuwe-modus-sequentie bouwen,
met feedback en timeouts; het vermogen tot veilige omschakeling is nog niet bewezen.

Een plan krijgt een snapshot-revisie, vervalt bij relevante bronwijzigingen en wordt
vóór uitvoering opnieuw op beschikbaarheid, overrides en grenzen gecontroleerd.
Een toekomstige executor serialiseert per installatie, dedupliceert gewenste waarden
en beperkt schrijffrequentie. Hij behandelt servicefouten en bevestiging van de
werkelijke toestand afzonderlijk; een succesvolle servicecall bewijst geen uitvoering.
Op herstart worden timer-/overridegegevens hersteld of conservatieve wachttijden
gebruikt. Er worden geen oude plannen blind opnieuw uitgevoerd.

VTherm en bestaande automations mogen in fase 2 niet tegelijkertijd met Zonentra de
bedrijfsmodus van dezelfde fysieke unit schrijven. Eigenaarsoverdracht is een
expliciete installatiekeuze; op basis van HA-context alleen kan Zonentra niet alle
handmatige bediening betrouwbaar herkennen. Zonentra 0.3 claimt geen eigenaarschap van apparaatbesturing.

## VTherm-analyse en hergebruik

Onderzocht op 12 oktober 2026: upstream manifest meldt VTherm 10.5.1. Zie
[LICENSE](https://github.com/jmcollin78/versatile_thermostat/blob/main/LICENSE),
[manifest](https://github.com/jmcollin78/versatile_thermostat/blob/main/custom_components/versatile_thermostat/manifest.json),
[self-regulation](https://github.com/jmcollin78/versatile_thermostat/blob/main/documentation/en/self-regulation.md),
[PI-algoritme](https://github.com/jmcollin78/versatile_thermostat/blob/main/custom_components/versatile_thermostat/pi_algorithm.py)
en [climate-controller](https://github.com/jmcollin78/versatile_thermostat/blob/main/custom_components/versatile_thermostat/thermostat_climate.py).

Ook de [configuratiehandleiding](https://github.com/jmcollin78/versatile_thermostat/blob/main/documentation/en/creation.md),
[basisinstellingen](https://github.com/jmcollin78/versatile_thermostat/blob/main/documentation/en/base-attributes.md)
en [Config Flow](https://github.com/jmcollin78/versatile_thermostat/blob/main/custom_components/versatile_thermostat/config_flow.py)
zijn onderzocht voor 0.3. VTherm scheidt centrale configuratie van het thermostaat-type
(zoals over_climate) en laat lokale instanties per parameterblok centraal overnemen
of eigen waarden kiezen. Zonentra gebruikt dat principe voor twee blokken, binnen
zijn bestaande singleton-entry. Het centrale configuratieprincipe blijft bruikbaar zonder VTherm-koppeling.

VTherm gebruikt een MIT-licentie, copyright Jean-Marc Collin (2022). Overname vereist
behoud van de copyright- en licentietekst. **Er is geen VTherm-code overgenomen.**
Daarmee krijgt Zonentra geen runtime- of forkafhankelijkheid van VTherm. Voor latere
codeovername moet de exacte upstream revisie worden vastgelegd en de betreffende
bestanden en transitieve dependencies opnieuw worden beoordeeld.

Technisch biedt over_climate-regeling externe ruimtetemperatuur, gecorrigeerde
climate-setpoints, PI-regeling, drempels en minimale tijd tussen correcties. Dit is
een bruikbaar referentiepunt voor de afwijkende Mitsubishi-interne sensor. Directe
klepregeling heeft een ander apparaatmodel en past niet automatisch op Mitsubishi.
Self-regulation en fanregeling zijn ruimtegedrag; zij lossen de gedeelde
heat/cool-beperking van twee buitenunits niet vanzelf op.

Het upstream manifest heeft geen verplichte HA-integratiedependencies, noemt
recorder/http als after_dependencies en numpy, scipy en vtherm_api>=0.5.0 als Python-
requirements. Zonentra importeert deze niet. Private VTherm-klassen zijn geen stabiel
contract. Gebruik eerst de standaard climate-entiteit voor observatie; eventuele
vtherm_api-integratie vereist een afzonderlijke compatibiliteits- en licentieaudit.
De huidige fanautomation blijft buiten Zonentra. VTherm-koppeling maakt geen deel
uit van het verdere implementatieplan.

## Diagnostiek en grenzen

De bestaande gebouwstatus blijft een overzicht van connectiviteit en fysieke
hold-simulatie. Per ruimte en per groep is er één extra diagnostische enum-sensor;
scores, temperaturen en verklaringen staan in begrensde attributen. De gebouwsensor
bevat maximaal 20 equipment-beslissingen en een totaalcount. Sensorleeftijd,
bronkwaliteit en de actuele/gewilde/toegestane modus zijn afzonderlijk zichtbaar.
De export redigeert alle entityvelden, contactlijsten, namen, IDs en member_zone_ids;
er worden geen ruwe SourceStates geëxporteerd. Lokale sensoren bevatten wel de
relevante waarden en apparatuur-IDs voor uitleg.

Geen afzonderlijke buitenunitmeters: later zijn energie-inschattingen altijd als
estimated gemarkeerd, zonder HA measurement-statistieken te claimen. Zonentra 0.3 bevat
geen energiegetallen; gewogen klimaatscores zijn geen energiemetingen. Alarm → gebouwbezetting, mmWave-debounce, CO₂-regeling,
weerstation en planning worden pas in latere fases gebouwd. Meetvalidatie en
stale-detectie zijn nu wel geïmplementeerd; optionele context heeft nog geen beleidswerking.

## Nog te bepalen vóór actieve regeling

- Welke fysieke binnenunits horen bij buitenunit 1 en 2? Welke entities zijn VTherm,
  welke Mitsubishi/Intesis/KNX, en welke bestaande automations schrijven modi?
- Wat zijn de door Mitsubishi toegestane minimumlooptijden, omschakelvertragingen
  en beschikbare feedback? Ondersteunen de huidige gateways bevestiging?
- Welke comfortbanden, gebruikstijden, handmatige override-duur en alarmmapping
  horen bij het kantoor? Alarmstatus onbekend betekent geen bewezen afwezigheid.
- Welke gevels, dakramen en KNX-windbeveiligingen zijn werkelijk aanwezig?
- Welke meters zijn echte metingen, wat zijn hun eenheden en actualisatiepatronen?

- Voor de 0.5-simulatie: welke minimale aan-/uittijden en heat↔cool-wachttijd
  schrijft Mitsubishi voor (de standaarden 600/180/300 s zijn aannames)? Rapporteren
  de Intesis/KNX-entities een betrouwbare modus na een commando, en hoe snel?
  Welke automations zetten airco's aan (die starten nu ook een override)?

Deze vragen blokkeren read-only analyse niet, maar moeten vóór actieve regeling worden beantwoord. Er worden geen fysieke aannames automatisch als
configuratie ingevuld.

## Geverifieerde Home Assistant-bronnen

Officiële documentatie geraadpleegd op 12 oktober 2026; uitvoering getest met
Home Assistant **2026.10.1**, Python **3.14.8** en pytest-custom-component **0.13.372**.
Actuele schemas gebruiken `probatio`; de gebruikte API's zijn ook gecontroleerd in
de geïnstalleerde HA-broncode. Geen nieuwe installatie getest met oudere HA-versies.

- [Config Flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [Config entries en lifecycle](https://developers.home-assistant.io/docs/config_entries_index/)
- [Options Flow en automatische reload](https://developers.home-assistant.io/docs/core/integration/options_flow/)
- [Getypeerde runtime_data](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/runtime-data/)
- [Event helpers](https://developers.home-assistant.io/docs/integration_listen_events/)
- [Diagnostics](https://developers.home-assistant.io/docs/core/integration/diagnostics/)
- [Manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Tests](https://developers.home-assistant.io/docs/development_testing/)
