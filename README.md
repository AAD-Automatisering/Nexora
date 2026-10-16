# Zonentra — Intelligent Building Management

Een lokaal, modulair gebouwbeheersysteem als native Home Assistant Custom Integration.
**Eén Home Assistant = één Zonentra = één gebouw**, met meerdere ruimtes en installaties.

Zonentra observeert bestaande Home Assistant-entiteiten, berekent de klimaatvraag
per ruimte en coördineert gedeelde buitenunitgroepen. De huidige versie ondersteunt
actieve standregeling, ruimteregeling, setpoints, ventilatorstanden, lamellen en
zonwering. Aanwezigheid, beweging en de weersverwachting beïnvloeden de regeling.

**Actieve standregeling** staat per buitenunitgroep standaard aan. De schakelaar
blokkeert bij uitschakelen alle HVAC- en lamelcommando's voor die groep.
**Ruimteregeling** en **Zonweringregeling** staan per ruimte standaard uit; hun
plannen blijven zichtbaar voordat de betreffende aansturing wordt ingeschakeld.
Lamellen volgen de modus van draaiende binnenunits zolang de groep is vrijgegeven.

Vloerverwarming en gebouwventilatie worden alleen als gekoppelde apparatuur
geobserveerd. De 16 °C-vloerverwarmingsgrens blijft intact. De oudere configuratie
met één item berekent alleen plannen; actieve aansturing gebruikt de centrale
configuratie met aparte ruimte-items. De versiegeschiedenis staat in
[ROADMAP.md](ROADMAP.md).

## Installatie

Getest met Home Assistant **2026.10.1**; oudere versies zijn niet ondersteund of getest.
De runtime heeft geen aanvullende Python-requirements en vereist geen VTherm.

1. Kopieer `custom_components/zonentra` uit dit project naar
   `<Home Assistant config>/custom_components/zonentra`.
2. Herstart Home Assistant.
3. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen → Zonentra**
   en kies **Centrale configuratie** (eenmalig): gebouwnaam en buitentemperatuursensor.
4. Open bij de centrale configuratie **Configureren**: een menu met **Algemeen**,
   **Aanwezigheid**, **Ruimteregeling**, **Zonwering**, **Weersverwachting** en de
   buitenunitgroepen. Pas per onderwerp aan en kies **Opslaan**.
5. Voeg daarna per ruimte opnieuw **Zonentra** toe en kies **Ruimte**: sensor,
   binnenunits (bestaande climate-entiteiten), buitenunitgroep en optionele context.

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

### Bijwerken naar 0.13.6 — vaste mogelijkheden voor HomeKit

HomeKit Bridge legt de onderdelen van een accessoire (zoals de ventilator en de
modi) vast op het moment dat het start. Was een airco op dat moment niet beschikbaar
(bijvoorbeeld tijdens een herstart, KNX nog niet klaar), dan miste de
Zonentra-thermostaat zijn modi en ventilatorstanden en kreeg HomeKit een ander
accessoire dan bij een ruimte waar de airco wel klaar was. Zonentra onthoudt nu per
ruimte de laatst bekende modi en ventilatorstanden van de airco's en biedt die
altijd aan. Na deze update eenmalig alle Zonentra-thermostaten in HomeKit resetten:
actie `homekit.reset_accessory` met alle Zonentra-thermostaten.

### Bijwerken naar 0.13.5 — ventilator standaard automatisch

Heeft een thermostaat geen ventilatorstand gekozen, dan regelt Zonentra de
ventilator nu automatisch (met **Ruimteregeling** aan); de thermostaat toont dan
**Auto**. Een vaste stand die je op de thermostaat kiest, geldt net als een
handmatige temperatuur voor de duur van de handmatige bediening (standaard 30
minuten, attribuut `fan_until`); daarna is de ventilator weer automatisch. Een
stand die iemand op de roomcontroller kiest, wordt niet teruggezet; bij de volgende
automatische stand neemt Zonentra het weer over.

Wil je dat medewerkers in een ruimte zelf de ventilator kiezen, zet dan op het
ruimteapparaat de schakelaar **Automatische ventilator** uit (standaard aan, alleen bij
ruimtes met binnenunits). Zonentra laat de ventilator daar dan helemaal met rust en
de thermostaat toont geen ventilator meer (in HomeKit: accessoire resetten).

### Bijwerken naar 0.13.4 — airco's blijven aan bij het wijzigen van instellingen

Een wijziging in de centrale configuratie (of een ruimte toevoegen) herlaadt
Zonentra. Tot 0.13.3 begon het daarna zonder geheugen: handmatige bediening,
hysterese en lopende commando's waren vergeten, waardoor geregelde ruimtes hun
airco konden uitzetten. Nu neemt de nieuwe regeling het geheugen over (binnen
dezelfde Home Assistant-sessie). Daarnaast blijft een draaiende airco aan zolang zijn
ruimte nog om warmte of koeling vraagt, ook als de totale vraag van de buitenunit te
klein is om een stand te kiezen. En zet een medewerker de zonwering vlak nadat
Zonentra hem bewoog weer anders (binnen de bevestigingstijd van 4 minuten), dan geldt
dat nu ook als handmatige bediening.

### Bijwerken naar 0.13.0 — centrale configuratie per onderwerp

Werk bij via HACS, herstart Home Assistant en herlaad de browser volledig.
**Configureren** bij de centrale configuratie opent nu een menu per onderwerp
(algemeen, aanwezigheid, ruimteregeling, zonwering, weersverwachting,
buitenunitgroepen) in plaats van één lang scherm. Je instellingen blijven staan; een
onderwerp wijzigt alleen zijn eigen velden. Een nieuwe centrale configuratie vraagt
alleen nog de naam en de buitentemperatuursensor.

### Bijwerken naar 0.12.0 — weersverwachting

Werk bij via HACS, herstart Home Assistant en herlaad de browser volledig. Kies in
**Centrale configuratie** de weerentiteit (`weather.`, met uurverwachting). Het
centrale apparaat krijgt daarna de sensoren **Verwachte maximumtemperatuur**,
**Verwachte minimumtemperatuur** en **Dagtype**, en de instellingen **Warme dag
vanaf**, **Koude dag tot** en **Startmarge**. Zonder weerentiteit verandert er niets.

### Bijwerken naar 0.11.0 — zonwering

Werk bij via HACS, herstart Home Assistant en herlaad de browser volledig. Vul daarna
in **Centrale configuratie** de sensor met het vermogen van de zonnepanelen en de
drempel in (en eventueel een windalarm als blokkering), en per ruimte bij
**Configureren** de **gevel** van de zonwering. De schakelaar **Zonweringregeling** op
het ruimteapparaat staat standaard uit: kijk eerst een paar dagen naar de sensor
**Zonwering** voordat je hem aanzet.

### Bijwerken naar 0.10.0 — ruimtesensoren, raam, ventilator en lamel

Werk bij via HACS, herstart Home Assistant en herlaad de browser volledig. Iedere
ruimte krijgt de nieuwe sensoren en de schakelaar **Raambypass** vanzelf. De vaste
comfort-, eco- en afwezig-grenzen staan niet meer in de wizard maar op de apparaten:
het centrale apparaat voor het hele gebouw (je bestaande waarden blijven staan) en
het ruimteapparaat om per ruimte af te wijken. Raamcontacten
die je al bij een ruimte had gekoppeld, doen nu echt iets: een open raam stopt de
ruimte na 30 s (centraal instelbaar). Voor de lamel vul je per ruimte bij
**Configureren** de lamel-entiteit en de standen voor koelen en verwarmen in.

### Bijwerken naar 0.9.0 — Zonentra-thermostaat per ruimte

Werk bij via HACS, herstart Home Assistant en herlaad de browser volledig. Iedere
ruimte krijgt op haar apparaat een thermostaat (met de naam van de ruimte), twee
instellingen voor de comfortband, een sensor **Actieve band** en de schakelaar
**Ruimteregeling**. Die schakelaar staat standaard **uit**: tot je hem aanzet,
verandert er niets aan wat Zonentra aanstuurt. Begin met één ruimte en controleer
eerst de sensor **Regelactie** van de binnenunit. Zet voor een geregelde ruimte
andere regelingen uit die dezelfde airco's aan/uit zetten of hun setpoint wijzigen
(zoals Versatile Thermostat of eigen automations).

### Bijwerken naar 0.8.0 — aanwezigheid en beweging

Werk bij via HACS, herstart Home Assistant en herlaad de browser volledig. Stel
daarna in **Centrale configuratie** de aanwezigheidssensor van het gebouw en de
eco- en afwezig-band in. Het bestaande veld "aanwezigheidssensor" van een ruimte
is nu de **bewegingssensor** van die ruimte. Let op: een ruimte met een
bewegingssensor zonder recente beweging gaat naar de eco-band, en dat werkt via
de klimaatvraag ook door in de actieve standregeling.

### Bijwerken naar 0.7.0 — actieve standregeling

**Let op: na de update stuurt Zonentra direct de stand van je airco's aan.**

1. Zet je eigen automation uit die de airco-stand (verwarmen/koelen) voor alle
   binnenunits zet, en de bijbehorende keuzehelper. Zonentra neemt die taak over;
   twee systemen tegelijk werken elkaar tegen.
2. Werk Zonentra bij via HACS en herstart Home Assistant.
3. Controleer per buitenunitgroep de schakelaar **Actieve standregeling** op het
   centrale apparaat. Die staat standaard aan; zet hem uit om alle commando's voor
   die groep direct te stoppen.

Alleen de nieuwe opbouw (centrale configuratie + ruimtes) stuurt aan. Een oud
enkel Zonentra-item blijft puur simulatie.

### Bijwerken naar 0.6.0

Na de update blijft je bestaande Zonentra-item werken, maar het is verouderd:
Home Assistant toont een reparatiemelding. Overstappen gaat zo:

1. Noteer je instellingen (grenzen, groepen, ruimtes en gekoppelde airco's).
2. Verwijder het oude Zonentra-item.
3. Voeg Zonentra toe → **Centrale configuratie**, en voeg via **Configureren** de
   buitenunitgroepen toe.
4. Voeg Zonentra per ruimte toe → **Ruimte**.

De entity-ID's veranderen: ruimtesensoren horen voortaan bij het apparaat van die
ruimte. De groeps- en gebouwsensoren horen bij het centrale apparaat. De
berekeningen zelf zijn ongewijzigd. Herlaad daarna de browserpagina volledig.

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

Zonentra 0.6 gebruikt dezelfde opbouw als Versatile Thermostat:

| Item | Hoeveel | Inhoud | Bewerken |
|---|---|---|---|
| Centrale configuratie | één per installatie | gebouwnaam, centrale grenzen en parameters, buitentemperatuur, handmatige bediening, anti-pendel en de **buitenunitgroepen** | Configureren → Centrale configuratie / Buitenunitgroep / Opslaan |
| Ruimte | één per ruimte | naam, temperatuursensor, binnenunits, buitenunitgroep, weging, "centrale waarden gebruiken" of eigen waarden, optionele aanwezigheid/vocht/CO₂/contacten, vloerverwarming, zonwering en ventilatie | Configureren bij de ruimte |

Een ruimte kun je pas toevoegen als de centrale configuratie bestaat. Zet je
**Centrale klimaatgrenzen gebruiken** of **Centrale regelparameters gebruiken**
uit, dan vraagt een tweede stap de eigen waarden. Eerder ingevulde eigen waarden
blijven bewaard als je teruggaat naar centraal.

Koppel elke binnenunit aan zijn werkelijke ruimte en kies de buitenunitgroep;
Zonentra raadt die relatie niet. Een binnenunit kan maar aan één ruimte gekoppeld
zijn; een tweede koppeling geeft een duidelijke foutmelding. Meerdere binnenunits
per ruimte zijn mogelijk. Een groep die nog door een ruimte wordt gebruikt, kan
niet worden verwijderd. Nieuwe koppelingen moeten in HA bestaan.

Elke ruimte krijgt een eigen apparaat met **Klimaatvraag** en per binnenunit de
**Binnenunit-modus** en de **Gesimuleerde actie**. Het centrale apparaat bevat de
**Status** en per buitenunitgroep de groepssensoren. Een ruimte toevoegen, wijzigen
of verwijderen werkt de centrale berekening automatisch bij. Een ruimte zonder
centrale configuratie start niet.

Het oude enkele Zonentra-item (vóór 0.6) blijft voorlopig werken met de vorige
opties-menu's, maar is verouderd. Centrale alarmmapping, ventilatie-/CO₂-regeling,
P1/PV en weeroptimalisatie volgen in latere fases.

## Klimaatintelligentie configureren

Begin via **Configureren** bij de centrale configuratie (onderwerpen **Algemeen**,
**Aanwezigheid**, **Ruimteregeling**, **Zonwering** en **Weersverwachting**; de vaste
grenzen staan op het centrale apparaat):

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
| Aanwezigheid gebouw | Optioneel; binary_sensor, input_boolean, alarmpaneel, persoon, groep of zone |
| Eco-band | 19 / 26 °C; geldt bij geen beweging in een ruimte met bewegingssensor |
| Afwezig-band | 16 / 30 °C; geldt als het gebouw afwezig is |
| Bewegingsdetectie / nalooptijd | 30 s / 30 min |

Bewerk daarna een ruimte via **Opties → Ruimte toevoegen of bewerken**:

| Ruimte-instelling | Gebruik |
|---|---|
| Ruimtetemperatuursensor | De externe KNX-temperatuursensor |
| Centrale klimaatgrenzen gebruiken | Standaard aan. Uit: de volgende stap vraagt alleen om grensentiteiten voor deze ruimte. Vaste grenzen stel je sinds 0.10 in op het apparaat (zie hieronder) |
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

| Binnenunit Regelactie | turn_on_heat / turn_on_cool / turn_off / correct_mode / hold / blocked | simulation (false bij ruimteregeling), room_regulation, room_regulation_status, setpoint_status, setpoint_target, setpoint_base, setpoint_offset, last_commands, zone, observed_mode, desired_mode, zone_demand, intended_action, steps, reason, blocked_reason, blocked_until, manual_override_active, override_remaining_seconds, override_expires_at, seconds_since_transition, group_coordination_phase, availability, evaluated_at |
| Buitenunit Gesimuleerde coördinatie | idle / preparing / stopping / waiting / applying / verifying / completed / blocked / failed | simulation, desired_mode, group_mode, group_mode_reason, coordinated_mode, derived_mode, member_indoor_units, available_indoor_units, conflicts, switch_needed, switch_from, switch_to, switch_allowed_in_simulation, active_switch_permitted (altijd false), phase_reason, waiting_until, blockers, planned_actions |

### Grenzen op de apparaten (0.10)

Zoals de presettemperaturen bij Versatile Thermostat:

| Apparaat | Instellingen |
|---|---|
| Centraal apparaat | Comfort verwarmen tot / koelen vanaf, Eco verwarmen tot / koelen vanaf, Afwezig verwarmen tot / koelen vanaf. Direct actief, zonder herladen |
| Ruimteapparaat | Dezelfde zes, voor deze ruimte — alleen als **Centrale klimaatgrenzen gebruiken** in de ruimteconfiguratie uit staat (sinds 0.13.3) |

Staat **Centrale klimaatgrenzen gebruiken** aan, dan gelden altijd de centrale
grenzen en heeft de ruimte geen eigen grenzen. Zet je de keuze uit, dan krijgt de
ruimte eenmalig de centrale grenzen als eigen startwaarden; daarna wijzig je ze op
het ruimteapparaat en volgen ze het centrale apparaat niet meer. Weer aanzetten wist
de eigen grenzen.

Een band moet geldig blijven: verwarmen + 2 × hysterese < koelen. Grensentiteiten
(`input_number` e.d.) stel je nog wel in de wizard in.

### Weersverwachting (0.12)

Zonentra vraagt elke 30 minuten de uurverwachting van de weerentiteit op
(`weather.get_forecasts`) en kijkt naar de komende 12 uur. Het verwachte maximum
bepaalt het **dagtype**:

| Dagtype | Verwacht maximum (standaard) | Verwarmen | Koelen | Zonwering (zon op de gevel, geen vraag) |
|---|---|---|---|---|
| Warm | vanaf 22 °C | Start pas 1 °C later (de zon warmt de ruimte toch op) | Normaal | Bezette ruimte: al omlaag; lege ruimte: omlaag |
| Neutraal | tussen beide | Normaal | Normaal | Bezette ruimte: op de ruimtetemperatuur; lege ruimte: omlaag |
| Koud | tot 12 °C | Normaal | Start pas 1 °C later (die warmte is gratis) | Omhoog (gratis zonnewarmte) |

- **Minder omschakelen:** een koele ochtend op een warme dag zet de buitenunit niet op
  verwarmen; een ruimte die op een koude dag door de zon iets te warm wordt, zet hem
  niet op koelen. Een lopende vraag eindigt zoals altijd; vorst- en
  oververhittingsbeveiliging veranderen niet.
- **Lege ruimte** (eco of afwezig): de zonwering kiest puur op energie — omlaag tegen
  opwarming, op een koude dag omhoog voor gratis warmte.
- **Instelbaar** op het centrale apparaat: warme dag vanaf, koude dag tot en de
  startmarge (0–3 °C).
- **Geen verwachting** (geen weerentiteit, storing of ouder dan 3 uur): dagtype
  onbekend, alles werkt zoals in 0.11. Na een mislukte eerste poging probeert
  Zonentra het na 2 minuten opnieuw.

### Zonwering (0.11)

Per zonwering (een `cover` met positie) beslist Zonentra, in deze volgorde:

| Situatie | Zonwering |
|---|---|
| Zon onder de horizon | Omhoog |
| Zon onbekend (geen zonnepanelen-sensor, stand onbekend) | Ongewijzigd |
| Geen zon (vermogen onder de drempel) of zon niet op deze gevel | Omhoog (daglicht) |
| Zon op de gevel en de ruimte vraagt verwarming | Omhoog (gratis zonnewarmte) |
| Zon op de gevel en de ruimte vraagt koeling | Omlaag |
| Zon op de gevel, geen vraag | Omlaag als de ruimte in de warme helft van haar band zit, anders omhoog (met 0,5 °C hysterese) |

- **Zon schijnt:** vermogen van de zonnepanelen boven de drempel, 5 minuten lang;
  pas weer "geen zon" na 15 minuten onder 70 % van de drempel (tegen wolken).
- **Zon op de gevel:** stand van de zon (`sun.sun`) hoger dan 5° en hooguit 80° naast
  de richting van de gevel (noord, oost, zuid, west en tussenrichtingen).
- **Klimaat weegt het zwaarst:** de band die nu geldt (comfort, eco, afwezig) en de
  klimaatvraag van de ruimte bepalen omhoog of omlaag.
- **Bewegen:** hooguit eens per 15 minuten per zonwering, alleen bij minstens 10 %
  verschil, naar de centraal ingestelde zonweringsstand (standaard 0 % = helemaal
  omlaag) of 100 % (open).
- **Mensen gaan voor:** wie de zonwering bedient via Home Assistant of de
  roomcontroller, wordt 2 uur gerespecteerd (centraal instelbaar). Een automation
  telt niet als bediening.
- **Wind en regen** regelt KNX zelf. Geef je centraal een blokkeer-entiteit op
  (bijvoorbeeld het windalarm), dan staat alleen een geldige `off`-state beweging
  toe. Bij `on`, ontbrekende, onbekende of onbeschikbare states blijft de zonwering
  stil (`blocked` of `block_unknown`).
- **Ontbrekende bronnen:** onbeschikbare covers krijgen geen commando
  (`cover_unavailable`). Zodra de cover terugkomt, beoordeelt Zonentra de beweging
  opnieuw; herstel telt niet als handmatige bediening. Mislukte serviceaanroepen
  worden na twee minuten opnieuw beoordeeld en tellen niet als geslaagde beweging.
- **Zonstand:** centraal onder Zonwering kies je de zonstand-entiteit (standaard
  `sun.sun`). Zonder geldige azimut en elevatie houdt Zonentra de schermen stil en
  verschijnt een melding bij **Instellingen → Systeem → Reparaties**. Die verdwijnt
  zodra de bron herstelt. Schakel hiervoor de Sun-integratie in.
- **Ruimteapparaat:** per zonwering een sensor **Zonwering gewenst** (omhoog / omlaag /
  ongewijzigd): wat Zonentra wil, niet de stand van de zonwering zelf (die staat in
  het attribuut `current_position`). Verder reden, beoogde stand, status, gevel, zon en
  de laatste commando's; de schakelaar **Zonweringregeling** (standaard uit =
  simulatie: de zonwering beweegt dan niet, de sensor geeft alleen advies).

### Meeting rooms voorbereiden met een agenda

Koppel bij **Configureren** van elke meeting room de eigen **Ruimteagenda**
(`calendar`-entiteit). Zet **Ruimteregeling** voor die ruimte aan en laat de
thermostaat verwarmen en/of koelen toestaan. De voorbereiding gebruikt de
comfortband die al voor die ruimte geldt; je hoeft geen losse HA-automation te maken.

Zonentra leest de afspraken voor de komende 24 uur en bepaalt per ruimte wanneer
het verwarmen of koelen moet beginnen. De schatting gebruikt het verschil tussen
de gemeten ruimtetemperatuur en de comfortband, het opwarm-/afkoeltempo en een
veiligheidsmarge. De buitentemperatuur telt mee: bij winterkou begint verwarmen
eerder dan bij zacht weer; bij hitte kan koelen langer duren.

- **Leren per ruimte en omstandigheden:** verwarmings- en koeltempo worden apart
  geleerd voor vorst (< 0 °C), koud (0–10), zacht (10–20), warm (20–30) en heet
  (≥ 30 °C). Een tempo uit het voorjaar wordt dus niet als wintertempo gebruikt.
  Leren gebruikt alleen nieuwe, valide sensorrapporten met hun eigen tijdstip;
  een timer maakt van een oude temperatuur geen nieuwe meting.
  De buitentemperatuur komt van de centrale buitensensor, of, als die niet is
  ingesteld, van de actuele temperatuur van de ingestelde weerentiteit.
- **Begin zonder meetgeschiedenis:** standaard is het starttempo 0,05 °C/min,
  aangepast voor buitenomstandigheden en conservatiever bij onbekende
  buitentemperatuur. Dit is een beginschatting, geen gemeten capaciteit. Na twee
  bruikbare meetintervallen gebruikt Zonentra het geleerde tempo voor die
  buitenconditie. Het leert tijdens actieve ruimteregeling uit intervallen van
  5–30 minuten, zonder open raam, handmatige apparaat-override of groepsblokkade.
  Geleerde tempo’s blijven bewaard na een HA-herstart.
- **Grenzen:** standaard 10 minuten marge en maximaal 180 minuten voorbereiding,
  per ruimte instelbaar. Voorbeeld: 2,3 °C opwarming met een geleerd wintertempo
  van 0,025 °C/min vraagt ongeveer 102 minuten inclusief marge; bij 0,1 °C/min
  in zacht weer ongeveer 33 minuten. De maximale voorbereiding begrenst dit.
- **Voorbereiding en afspraak:** de comfortband geldt ook als de gebouw-aanwezigheid
  nog afwezig meldt. Na afloop volgt de ruimte weer aanwezigheid en beweging.
  Zonder bewegingssensor gebruikt een ruimte met agenda tussen afspraken eco
  (of afwezig als het gebouw afwezig is). Met beweging blijft ook ongepland
  gebruik mogelijk.
- **Actualiseren:** agenda’s worden elke vijf minuten en bij een agenda-statewijziging
  opnieuw gelezen. Voorbereidingsstart, afspraakstart en einde krijgen daarnaast
  een timer. Annuleringen en verschuivingen tellen bij de volgende agenda-update
  mee. Overlappende afspraken houden comfort aaneengesloten; afspraken voor een
  hele dag worden genegeerd. Titels, beschrijvingen en locaties worden niet bewaard.
- **Bediening en blokkades:** een uitgeschakelde ruimteregeling, thermostaat of
  groepsstop wordt door de agenda niet ingeschakeld. Raambeveiliging,
  herstartvertragingen en de gezamenlijke buitenunitmodus blijven gelden. Bij een
  niet bruikbare agenda valt de ruimte terug op de gewone aanwezigheidsregeling.

De sensor **Afspraakvoorbereiding** op het ruimteapparaat toont de status, de
volgende afspraak, berekende voorbereidingsstart, voorbereidingstijd en of het
tempo geleerd is. Het blijft een schatting: controleer tijdens de eerste
praktijkperiode of de ruimtes bij aanvang de gewenste comfortband halen en pas
zo nodig de marge of maximale voorbereiding aan.

### Ruimtesensoren, raam, ventilator en lamel (0.10)

| Entiteit op het ruimteapparaat | Betekenis |
|---|---|
| **Aanwezigheid** | Aanwezigheid van het gebouw zoals die voor deze ruimte geldt (`present`, `absent`, `unknown`), met beweging als attribuut; zonder gebouwaanwezigheid volgt hij de bewegingssensor van de ruimte. Alleen met een aanwezigheids- of bewegingssensor (sinds 0.13.3) |
| **Veiligheid** | `safe`, of `sensor_fault` als de ruimtetemperatuur niet te vertrouwen is; dan regelt Zonentra niet op temperatuur |
| **Raam** | `closed`, `opening` (open, wacht op de vertraging), `open`, `bypass`, `unknown` — alleen met raam-/deurcontacten (sinds 0.13.3) |
| **Raambypass** (schakelaar) | Negeert een open raam in deze ruimte — alleen met raam-/deurcontacten (sinds 0.13.3) |
| **Geregeld setpoint** | Het setpoint waar Zonentra de binnenunit naartoe stuurt (of zou sturen) — alleen met binnenunits, net als de schakelaar **Ruimteregeling** en de automatische ventilatorstand (sinds 0.13.3) |
| **Gemiddelde temperatuur** | Exponentieel gemiddelde van de ruimtetemperatuur (tijdconstante 5 min) |
| **Temperatuurtrend** | Hoe snel de ruimte opwarmt (+) of afkoelt (−), in °C per uur |
| **Automatische ventilatorstand** | De stand die de automatische ventilator nu kiest; sinds 0.13.3 altijd zichtbaar (ook als simulatie of met een andere ventilatorstand), attribuut `in_use` zegt of de thermostaat op `auto` staat |

- **Open raam:** na de vertraging vraagt de ruimte niets meer. Met Ruimteregeling gaan
  draaiende units direct uit (ook binnen de minimale aantijd) en gaat er niets aan tot
  het raam dicht is. Een onbekend contact telt als dicht.
- **Automatische ventilator:** de thermostaat biedt `auto` als de units zelf geen
  automatische stand hebben. Met Ruimteregeling kiest Zonentra dan per 0,5 °C afstand
  tot het doel één stand hoger (bij jullie unit 25 → 50 → 75 → 100%), hooguit eens per
  setpoint-wachttijd. De graden per stand stel je in bij Configureren →
  **Ruimteregeling** (0,2–2 °C, standaard 0,5; sinds 0.13.1). In `dry` en `fan_only` draait de laagste stand.
- **Lamel:** stel per ruimte een select-, number- of schakelaar-entiteit in met een
  stand voor koelen (omhoog) en verwarmen (omlaag); bij een schakelaar (bijvoorbeeld
  KNX "vane auto/stop", DPT 1.001) zijn de standen `on` of `off`. Zodra een unit van de ruimte gaat koelen
  (of drogen) of verwarmen, zet Zonentra de lamel eenmaal in die stand; ook zonder
  Ruimteregeling, want het volgt alleen wat de unit al doet. Na uitschakelen wordt hij
  bij de volgende start opnieuw gezet; met de hand verplaatsen wordt niet teruggedraaid.
- Energie en overbelasting (Versatile Thermostat) ontbreken bewust: daarvoor is een
  vermogensmeter per airco nodig.

### Zonentra-thermostaat en ruimteregeling (0.9)

Iedere ruimte heeft een eigen thermostaat (climate-entiteit) op haar apparaat:

| Onderdeel | Betekenis |
|---|---|
| Modus `heat` | Alleen verwarmen; het doel is de verwarmingsgrens. Een te warme ruimte vraagt niets |
| Modus `cool` | Alleen koelen; het doel is de koelgrens. Een te koude ruimte vraagt niets |
| Modus `heat_cool` (of `auto`) | Beide: binnen de comfortband houden (onder- en bovengrens). Heten de binnenunits deze stand `auto`, dan heet hij op de thermostaat ook zo |
| Modus `dry` / `fan_only` | Alleen als alle binnenunits van de ruimte het kennen. De ruimte vraagt geen verwarming of koeling; met ruimteregeling draaien de units in die stand (`dry` alleen als de groep koelt) |
| Modus `off` | De ruimte vraagt niets |
| Ventilatorstand | De standen die alle binnenunits kennen; met ruimteregeling krijgt een draaiende unit de gekozen stand (eenmaal per wijziging) |
| Doel / onder- en bovengrens | De grenzen van de band die nu geldt. Een doeltemperatuur wijzigen op de thermostaat is een **tijdelijke handmatige afwijking** (de actieve preset blijft zichtbaar): de configuratie verandert niet. Net als bediening via de roomcontroller geldt hij de Manual Override-duur (standaard 30 minuten, attribuut `manual_until`), en korter als je een preset kiest of de band wisselt (aanwezigheid, beweging). Vaste grenzen stel je in op het apparaat |
| Preset `comfort` (standaard) | Comfortband; zonder beweging eco en bij een afwezig gebouw afwezig (0.8). De thermostaat toont dan ook preset Eco of Afwezig met die grenzen, en springt terug naar Comfort zodra er weer iemand is |
| Preset `eco` / `away` | Vaste band; een afwezig gebouw gaat altijd voor |
| Comfort verwarmen tot / koelen vanaf | Dezelfde comfortband als instellingen op het apparaat |
| Sensor **Actieve band** | Welke band nu geldt, met reden en grenzen |
| Schakelaar **Ruimteregeling** | Standaard uit (simulatie). Aan: Zonentra regelt de binnenunits van deze ruimte echt |

De thermostaat neemt zo de opties van de binnenunits over, zodat hij ze in HomeKit en
dashboards kan vervangen. Het zijn de standaardmodi van Home Assistant, maar een modus bepaalt nooit de stand
van de buitenunit: de groep weegt de vraag van alle ruimtes. Een ruimte op `heat`
telt alleen mee als ze warmte vraagt; draait de groep op koelen, dan wacht ze tot de
groep weer verwarmt. Een ruimte op `off` telt niet mee.

Met **Ruimteregeling** aan:

- Een binnenunit gaat **aan** bij klimaatvraag, maar alleen in de stand waarin de
  buitenunit al staat (de klaargezette stand van de standregeling, of zonder
  standregeling de stand van de units die al draaien). Zonentra kiest hiermee
  nooit zelf een tegengestelde stand.
- Een binnenunit gaat **uit** als de ruimte niets meer vraagt, of als de thermostaat
  uit staat. De minimale aan- en uittijden blijven gelden.
- Het **setpoint** van een draaiende unit wordt bijgestuurd op de ruimtesensor.
  Basis is de rand van de band (verwarmen: verwarmingsgrens + hysterese; koelen:
  koelgrens − hysterese); daar komt de afwijking van de ruimte bij (verwarmen:
  setpoint = basis + (basis − ruimte)), begrensd tot 2 °C en hooguit eens per 5
  minuten (beide centraal instelbaar), afgerond op de stap van de unit.
- Mensen gaan voor: zet iemand de unit aan of uit via de roomcontroller, of wijzigt
  iemand in Home Assistant het setpoint van de unit zelf, dan respecteert Zonentra dat
  voor de Manual Override-duur (standaard 30 minuten). Commando's die Zonentra zelf
  geeft, tellen niet als bediening. Een setpoint dat de unit of gateway zelf wijzigt
  (de roomcontroller kan alleen aan/uit), stuurt Zonentra na de wachttijd terug.
- Een klaarzet-puls van de standregeling zet een unit niet uit als de geregelde
  ruimte hem in die stand nodig heeft.
- In `dry` of `fan_only` zet Zonentra de units eenmaal in die stand (na de minimale
  uittijd); verandert iemand daarna de unit, dan blijft dat zo tot de thermostaat
  weer wijzigt. Gaat de groep naar verwarmen, dan gaat een drogende unit uit.
- De ventilatorstand van de thermostaat gaat eenmaal per wijziging naar draaiende
  units; een andere stand op de roomcontroller wordt niet teruggezet.
- **Ventilator in HomeKit (0.13.2):** de thermostaat noemt de standen van de units
  zoals Home Assistant ze kent: `auto`, `low`, `middle`, `medium`, `high` (bij vier
  standen 25/50/75/100%; bij drie low/middle/high, bij twee low/high). Daardoor toont
  HomeKit (via HomeKit Bridge) bij de thermostaat een ventilator met een
  snelheidsschuif en een automaatstand. Units met meer dan vier standen houden hun
  eigen namen. Zie je de ventilator in HomeKit nog niet, reset dan het accessoire:
  actie `homekit.reset_accessory` met de Zonentra-thermostaat.

De thermostaat wordt bewaard en overleeft herstarts. De sensor **Regelactie** van de
binnenunit toont `room_regulation`, `room_regulation_status`, `setpoint_status`,
`setpoint_target`, `setpoint_base`, `setpoint_offset` en de laatste commando's.

### Aanwezigheid en beweging (0.8)

Zoals bij Versatile Thermostat bepalen aanwezigheid (gebouw) en beweging (ruimte)
welke band voor de klimaatvraag geldt. Aanwezigheid gaat altijd voor.

| Situatie | Band | Standaard (verwarmen tot / koelen vanaf) |
|---|---|---|
| Aanwezig en beweging, of geen bewegingssensor | Comfort | de grenzen van de ruimte of het gebouw |
| Aanwezig, geen beweging | Eco | 19 / 26 °C |
| Gebouw afwezig | Afwezig | 16 / 30 °C |
| Aanwezigheid of bewegingssensor onbekend/onbeschikbaar | Comfort | niemand zit in de kou door een sensorfout |

Aanwezigheidsbronnen: binary_sensor of input_boolean (aan = aanwezig), alarmpaneel
(uitgeschakeld = aanwezig, ingeschakeld = afwezig), persoon (`home`), groep
(`on`/`home`) en zone (aantal personen > 0). Beweging telt pas na 30 s aanhoudende
detectie en blijft 30 min na de laatste beweging gelden (centraal instelbaar). De
klimaatvraagsensor toont `occupancy_mode`, `occupancy_reason`, `building_presence`
en `motion`; de status toont `building_presence`.

### Actieve standregeling (0.7)

Bij deze Mitsubishi-installatie bepaalt de **eerste binnenunit die aangaat** de
stand van de buitenunit; een unit in de andere stand doet dan niets, en er is geen
terugmelding van de werkelijke buitenunitstand. Zonentra houdt daarom alle
binnenunits van een groep klaargezet in de gewenste groepsmodus:

| Situatie | Wat Zonentra doet |
|---|---|
| Groepsmodus wisselt (na hysterese en minimale wisseltijd) | Lopende units stoppen eerst en wachten op de bevestigde uit-state en de omschakelpauze, daarna starten ze in de nieuwe stand; units die al uit stonden krijgen na hun minimale uit-tijd een korte puls (`set_hvac_mode` → 3 s → `turn_off`), zodat ze bij de volgende inschakeling in de juiste stand starten |
| Iemand zet een unit aan in de verkeerde stand | Na de bedieningsvertraging (minstens 30 s) en minimale aan-tijd stopt Zonentra de unit; na uit-bevestiging en omschakelpauze volgt de groepsmodus |
| Groepsmodus neutraal of onbekend (bijv. sensorfout) | Niets; de laatst gezette stand blijft |
| Schakelaar **Actieve standregeling** uit | Geen HVAC- of lamelcommando's meer voor deze groep: ook ruimteregeling, setpoints, ventilatorstanden en openstaande pulsen stoppen; het plan blijft zichtbaar als simulatie |

`fan_only` (en bij koelen `dry`) blijven ongemoeid. De laatst gezette stand wordt
bewaard, zodat een herstart niet opnieuw alle airco's laat pulsen. Na een herstart
stuurt Zonentra pas iets zodra de schakelaar is hersteld. Commando's die Zonentra
zelf geeft, starten geen Manual Override; een automation die een airco aanzet ook
niet meer (herkend aan de HA-context), de roomcontroller en een HA-gebruiker wel.

De sensor **Gesimuleerde coördinatie** van de groep toont `active_mode_control`,
`mode_control_status`, `preset_mode`, `preset_changed_at` en de laatste commando's
met resultaat. Statussen: `in_sync`, `group_mode_applied`, `corrected`,
`minimum_switch_interval`, `neutral`, `no_group_mode`, `disabled`,
`waiting_for_switch_state`, `climate_service_unavailable`. Actieve timing is zichtbaar
als `minimum_off_time`, `stopping_for_changeover`, `changeover_wait` of
`changeover_unit_unavailable`.

Een groepspreset wordt pas als toegepast opgeslagen nadat de moduscommando's
voor alle betreffende units zijn geslaagd. Tijdens het versturen is de status
`applying_preset`; bij een fout volgt `preset_retry`. Alleen de mislukte units
krijgen een herpoging, ook zonder nieuwe sensorupdates: eerst na twee minuten,
bij herhaald falen met oplopende wachttijd tot maximaal dertig minuten. De
uitschakelpuls wordt pas ingepland nadat het inschakelcommando is geslaagd. Een
mislukte of onbevestigde uitschakelpuls wordt opnieuw beoordeeld.

Serviceacceptatie en statebevestiging zijn apart zichtbaar: `result: sent` betekent
dat HA de aanroep accepteerde; `confirmation` toont `pending`, `confirmed`,
`timeout`, `not_sent` of `superseded`. HVAC-, setpoint-, ventilator- en lamelcommando’s
krijgen een bevestigingsdeadline van 60 seconden; covers behouden 240 seconden en
het bewegingsinterval van 15 minuten. Verlopen deadlines starten zelf een
herbeoordeling. Alleen nog gewenste en toegestane commando’s worden opnieuw
gepland. Dit bevestigt HA-states, geen fysieke compressorfeedback.

De dispatcher controleert direct vóór verzending opnieuw de groepsstop,
Ruimteregeling, FanControl, thermostaat-uit en handmatige override. Tijdens een
handmatige apparaat-override pauzeert ook de ventilatorregeling en na afloop
wordt de gewenste snelheid opnieuw beoordeeld. Een herstart van HA bewaart de
laatste preset; een gewone centrale reload bewaart ook een lopende omschakelpauze.

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
een herkenbare automation/script met `parent_id` start bij inschakelen geen
override. Een kale context kan van een roomcontroller komen en telt als handmatig.

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

De historische status `read_only` en het gelijknamige attribuut op de
gebouwstatus beschrijven de observatie- en analysegegevens. Ze geven niet aan
of de hele integratie apparaten aanstuurt. Bekijk daarvoor de groepsschakelaar,
**Ruimteregeling**, **Zonweringregeling** en het commandolog. De coördinatiesensor
meldt `read_only: false` zolang de groepsschakelaar aan staat. `degraded`
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
sensorleeftijd (alleen update_based) en wachttijden bij. Er is geen periodieke polling,
behalve de weersverwachting (elke 30 minuten, alleen met een weerentiteit).

## Veilig testen naast de bestaande regeling

Voor een vergelijking zonder aansturing zet je **Actieve standregeling** voor
alle groepen uit, en **Ruimteregeling** en **Zonweringregeling** voor alle ruimtes
uit. De groepsschakelaar staat standaard aan: zet die uit voordat je binnenunits
koppelt als je eerst alleen wilt observeren. Vergelijk per ruimte
de KNX-temperatuur, ingestelde analysegrenzen en weergegeven klimaatscores.
Controleer per buitenunit current/desired/proposed en de blokkeerreden. Test een
onbeschikbare bron en het herstel daarvan; Zonentra moet unknown melden in plaats
van een nieuwe modus bedenken. **Koppel de voorgestelde modi niet aan eigen
actuator-automations** als je deze versie read-only wilt testen. Dat geldt ook
voor de gesimuleerde acties uit 0.5: ze zijn bedoeld om te vergelijken met wat de
installatie werkelijk doet.

Aanwezigheid en raamcontacten zijn invoer voor de regeling; met Ruimteregeling
aan kan een open raam binnenunits uitschakelen. Zonwering beweegt wanneer
Zonweringregeling aan staat. Vloerverwarming en gebouwventilatie worden niet
aangestuurd; de gasvloergrens van 16 °C blijft intact. Wijs bij actieve aansturing
per apparaat aan welke regeling de modi en instellingen beheert.

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

Pure kernfuncties worden zonder HomeAssistant-instance getest. Integratietests
gebruiken de echte Home Assistant flow manager, state machine, platforms en
lifecycle-fixtures, met gemockte climate-services voor de actieve functies. Ze
controleren welke commando's worden gestuurd, en dat een ruimte zonder
ruimteregeling geen ruimtecommando's krijgt. CI voert dezelfde checks op Linux
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
  runtime.py                    HA-observatie, lifecycle en klimaatcoördinatie
  runtime_bookings.py           agenda’s, adaptieve voorbereiding en opgeslagen leertempo’s
  bookings.py                   pure afspraakvensters en tempo-inschatting
  runtime_shading.py            zonwering, herstel na uitval en zonstandmelding
  runtime_commands.py           service-uitvoering, bevestiging, back-off en commandolog
  runtime_timing.py             actieve stop/wacht/start voor groepen en zelfstandige units
  runtime_helpers.py            gedeelde commandobevestiging en herkomst van events
  indoor.py                     binnenunitobservatie en afgeleide groepsmodus
  override.py                   Manual Override-detectie en command tracking
  control.py                    groepscoördinatie en gesimuleerde acties per unit
  topology.py                   centrale configuratie + ruimte-items → één gebouwmodel
  executor.py                   actieve standregeling: welke modus-commando's nodig zijn
  presence.py                   aanwezigheid (gebouw) en beweging (ruimte) → comfort/eco/afwezig
  thermostat.py                 ruimtethermostaat, band, ruimteregeling en zelfregulerend setpoint
  roomstate.py                  raam, veiligheid, temperatuurtrend, automatische ventilator, lamel
  shading.py                    zonwering: zon, gevel, klimaat en bewegen
  temperature.py                temperatuur- en stapgrootteconversie
  entity.py                     gedeelde basis voor bedieningsentiteiten op het ruimteapparaat
  climate.py                    Zonentra-thermostaat per ruimte
  number.py                     comfortband als instellingen op het ruimteapparaat
  switch.py                     noodstop per buitenunitgroep en Ruimteregeling per ruimte
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

### Lokale ontwikkelomgeving

Gebruik Python 3.14.2 of nieuwer en maak de omgeving met een interpreter op een
vaste locatie; een verwijzing naar een interpreter in `/private/tmp` kan verdwijnen.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```
