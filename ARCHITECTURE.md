# Zonentra — architectuur

Status: fase 1, read-only fundament, 12 oktober 2026.

## Projectnaam en integratie-identiteit

Vanaf versie 0.1.2 heet het project **Zonentra**. De Home Assistant-domain is
`zonentra` en alle runtime-bestanden staan in `custom_components/zonentra`.
Config-entry unique ID, apparaatidentifiers en interne signalen gebruiken deze
domain. Omdat het project in de testfase zit, is er geen compatibiliteitslaag of
migratie van eerdere testconfiguraties. Installeer en configureer deze integratie
opnieuw; de README beschrijft de overgang.

## Scope en belangrijkste keuzes

**Eén Home Assistant-installatie = één Zonentra = één gebouw.** De Config Flow,
vaste unique ID en `single_config_entry` in het manifest begrenzen dit expliciet.
Meerdere ruimtes en fysieke installaties worden binnen dat gebouw gemodelleerd.
Er is geen multi-building beheerlaag. Het entry-ID vormt alleen een stabiele
namespace voor runtime en diagnostische entiteiten.

Zonentra coördineert uiteindelijk comfort, energie en installatiebeperkingen, maar
fase 1 observeert uitsluitend bestaande Home Assistant-entiteiten. De enige
gepubliceerde entiteit is een diagnostische sensor. Er zijn geen actuatorservices,
climate-platform, serviceregistraties of serviceaanroepen. De vloerverwarmingsgrens
van 16 °C wordt nergens als verstelbaar setpoint opgeslagen of geschreven.
Lokale KNX-veiligheid en bestaande VTherm/KNX/Shelly-automations blijven functioneren.

### Besluit A — pure kern en dunne HA-adapter

`models.py` en `decision.py` hebben geen Home Assistant-afhankelijkheid. `runtime.py`
leest state en publiceert updates, `config_flow.py` beheert de UI, `sensor.py` toont
status. Runtime staat in de getypeerde `ConfigEntry.runtime_data`.

Alternatief: tien managers met eigen eventbussen en onderlinge afhankelijkheden.
Dat levert voor het fundament veel levenscyclus- en synchronisatiewerk op. Daarom
zijn Building, Zone en Equipment nu datamodellen; er komen pas zelfstandige managers
als ze eigen gedrag nodig hebben. Geen lege implementaties voor toekomstige modules.

### Besluit B — voorstellen centraal arbitreren

Een toekomstige module mag alleen een voorstel indienen. Eén Decision Engine
beoordeelt alle voorstellen uit dezelfde snapshot en maakt één plan. Eén toekomstige
uitvoerlaag bezit de bevoegdheid om HA-services aan te roepen. Fase 1 bevat die laag
niet. Meerdere apparaten met hetzelfde fysieke entity-ID worden afgewezen.
Een ruimtecontroller en de fysieke binnenunit zijn aparte rollen: bij VTherm wordt
VTherm gekoppeld als `controller_entity` en de Mitsubishi-climate als apparatuur.
Een climate-entiteit mag beide rollen hebben als deze zelf de ruimtecontroller is;
het toekomstige eigenaarschapsbeleid moet dan één aansturingspad kiezen.

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
pollen, dus dit voegt geen waarde toe. Tijdsafhankelijke beslissingen krijgen later
expliciete timers bij een deadline, niet een onnodige algemene polling-loop.

## Datamodellen (geïmplementeerd)

| Model | Belangrijkste velden | Invariant |
| --- | --- | --- |
| Building | id, name, zones, groups, equipment | Eén gebouw per installatie |
| Zone | id, name, temperature_entity, controller_entity, occupancy_entity | Koppelingen optioneel; temperatuur apart van climate-interne meting |
| EquipmentGroup | id, name, single_hvac_mode=True | Een buitenunitgroep representeert gedeeld heat/cool-bedrijf |
| Equipment | id, name, kind, entity_id, zone_id, group_id | Eén zone per apparaat; groep alleen bij HVAC; fysieke entiteit uniek |
| Observation | state, quality | missing, unknown, unavailable of observed |
| Decision | equipment_id, action, reason | Fase 1: action uitsluitend hold |

Dataclasses voor de topologie zijn immutable en verzamelingen zijn tuples. Nieuwe IDs zijn automatisch gegenereerde UUIDs in hexnotatie. Bestaande IDs blijven
geldig en uniek per categorie: kleine letters/cijfers/`_`/`-` (maximaal 64 tekens).
Groepslidmaatschap loopt via apparatuur, zodat meerdere binnenunits per ruimte en
per buitenunit mogelijk zijn. Niet-HVAC-apparatuur kan zonder groep geregistreerd
worden als floor_heating, shading, ventilation of other. Equipment is een logisch
model voor een bestaande HA-entiteit, geen nieuw fysiek apparaat in de HA-registry.

De huidige observation is een eenvoudige statusobservatie, **geen verklaring dat
sensorwaarden betrouwbaar, recent of correct gekalibreerd zijn**. Fase 1 rekent geen
warmtevraag uit. Alleen expliciete states heat/cool tellen voor een waargenomen
buitenunitconflict; auto/heat_cool/hvac_action geven geen betrouwbaar bewijs van de
werkelijke buitenunitmodus. Zonentra corrigeert zo'n conflict niet.

Voor fase 2 wordt Observation uitgebreid met tijdstip, genormaliseerde eenheid,
bronkwaliteit en geldigheidsduur. Temperatuur krijgt checks op numerieke/finitie
waarden, plausibiliteit en bron-specifieke freshness. Een onveranderde goede KNX-
temperatuur mag niet zomaar als defect worden beschouwd omdat `last_changed` oud is.

## Modulegrenzen (ontwerp voor volgende fases)

De onderstaande interfaces zijn **Zonentra-ontwerpcontracten**, geen bestaande HA-API's
of al geïmplementeerde managers:

| Onderdeel | Input | Output / verantwoordelijkheid |
| --- | --- | --- |
| Building Manager | Topologie, planning, snapshots | Coördinatie van één gebouw en evaluatierondes |
| Zone Manager | Sensoren, gewenste comfortband, bezetting | ZoneSnapshot met kwaliteit en wensen |
| Equipment Manager | Topologie, gemelde modi, tijden, capabilities | EquipmentSnapshot en harde beperkingen |
| Climate Module | ZoneSnapshot, controllerdata | Warmte-/koelvoorstellen; later room-controller adapter |
| Shading Module | Zon, weer, gevel, lokale veiligheid | Schaduwvoorstel, invloed op koelvraag |
| Ventilation Module | CO₂, bezetting, beschikbaarheid | Ventilatievoorstel; luchtkwaliteit vóór kosten |
| Occupancy Module | Alarm, mmWave, timers | occupied / unoccupied / unknown per niveau |
| Energy Module | P1, PV, meters, tarieven | Energiecontext met measured/estimated/unknown provenance |
| Decision Engine | Alle voorstellen, harde beperkingen | Eén verklaarbaar plan met afwijzingen |
| Diagnostics | Snapshot, plan, redenen | Status, uitleg, privacybewuste export |

Een module krijgt een immutable snapshot en levert `Proposal`-waarden (module,
resource, intent, prioriteit, reden, geldig-tot); geen `hass` of uitvoeradapter.
`evaluate(snapshot, now) -> proposals` wordt de pure testbare grens. De Engine levert
`DecisionPlan` met gekozen én afgewezen voorstellen en reason codes. Een
RoomController-adapter observeert VTherm of een toekomstige eigen controller via
hetzelfde contract. Dependencies blijven één richting op: HA-adapter → kern.

## Prioriteiten en conflictpreventie (fase 2-ontwerp)

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
handmatige bediening betrouwbaar herkennen. Fase 1 claimt geen eigenaarschap.

## VTherm-analyse en hergebruik

Onderzocht op 12 oktober 2026: upstream manifest meldt VTherm 10.5.1. Zie
[LICENSE](https://github.com/jmcollin78/versatile_thermostat/blob/main/LICENSE),
[manifest](https://github.com/jmcollin78/versatile_thermostat/blob/main/custom_components/versatile_thermostat/manifest.json),
[self-regulation](https://github.com/jmcollin78/versatile_thermostat/blob/main/documentation/en/self-regulation.md),
[PI-algoritme](https://github.com/jmcollin78/versatile_thermostat/blob/main/custom_components/versatile_thermostat/pi_algorithm.py)
en [climate-controller](https://github.com/jmcollin78/versatile_thermostat/blob/main/custom_components/versatile_thermostat/thermostat_climate.py).

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
De huidige fanautomation blijft buiten Zonentra. Een eigen room controller kan later
dezelfde adaptergrens invullen zonder een VTherm-fork.

## Diagnostiek en grenzen

Sensorstatus: `read_only` bij observeerbare inputs (ook een leeg gebouw), `degraded`
bij missing/unknown/unavailable, `conflict` bij waargenomen tegenstrijdige groepsmodi.
Attributen tonen aantallen en hold-redenen. Dit is geen thermostaatadvies.
De diagnostiekdownload redigeert namen, IDs en entiteitkoppelingen, en bevat geen
ruwe bronstates, alarmwaarden of HA-attributen. Lokale sensorattributen bevatten
wel apparatuur-IDs zodat de gebruiker redenen kan herkennen.

Geen afzonderlijke buitenunitmeters: later zijn energie-inschattingen altijd als
estimated gemarkeerd, zonder HA measurement-statistieken te claimen. Fase 1 bevat
overhaupt geen energiegetallen. Alarm → gebouwbezetting, mmWave-debounce, CO₂,
weerstation, planning en stale-sensorbeleid worden pas in latere fases gebouwd.

## Nog te bepalen vóór actieve regeling

- Welke fysieke binnenunits horen bij buitenunit 1 en 2? Welke entities zijn VTherm,
  welke Mitsubishi/Intesis/KNX, en welke bestaande automations schrijven modi?
- Wat zijn de door Mitsubishi toegestane minimumlooptijden, omschakelvertragingen
  en beschikbare feedback? Ondersteunen de huidige gateways bevestiging?
- Welke comfortbanden, gebruikstijden, handmatige override-duur en alarmmapping
  horen bij het kantoor? Alarmstatus onbekend betekent geen bewezen afwezigheid.
- Welke gevels, dakramen en KNX-windbeveiligingen zijn werkelijk aanwezig?
- Welke meters zijn echte metingen, wat zijn hun eenheden en actualisatiepatronen?

Deze vragen blokkeren fase 1 niet. Er worden geen fysieke aannames automatisch als
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
