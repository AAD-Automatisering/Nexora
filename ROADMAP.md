# Zonentra — roadmap

Scope: één Home Assistant-installatie, één Zonentra, één gebouw. Alle fases moeten
kleine, onafhankelijk toetsbare stappen blijven. Deze basis doet geen automatische
hardware-aansturing.

## Fase 1 — fundament (0.1)

- [x] Architectuur en VTherm-referentie/licentieonderzoek.
- [x] Native Custom Integration met Config Flow, één gebouw en Options Flow.
- [x] Zones, sensor-/controllerkoppelingen, apparatuur en buitenunitgroepen.
- [x] Validatie van IDs, verwijzingen, domeinen en dubbele fysieke apparatuur.
- [x] Eventgedreven observatie, diagnostische status en geredigeerde export.
- [x] Pure hold-simulatie en detectie van waargenomen groepsconflicten.
- [x] Tests met echte HA-flow- en lifecycle-helpers; CI-configuratie.
- [x] Gebruiker heeft één ruimte/groep/apparaat in HA geconfigureerd en read_only bevestigd.

Exit: alle tests slagen; gebouw is via UI configureerbaar; geen servicecall vanuit
Zonentra; herladen ruimt listeners op. De praktijktest blijft een aparte installatie-
verificatie: unit/integratietests vervangen geen echte KNX/Mitsubishi-omgeving.

## Fase 2 — klimaatcoördinatie

### Versie 0.2 — Building Intelligence (geïmplementeerd)

- [x] Immutable ruimtesnapshots en gekoppelde installaties.
- [x] Temperatuurnormalisatie, bronkwaliteit en rapportgebaseerde stale-detectie.
- [x] Heat/cool/neutral/unknown met configureerbare hysterese en analysegrenzen.
- [x] Gewogen vraagscore per ruimte; deduplicatie binnen gedeelde buitenunitgroepen.
- [x] Centrale pure groepsarbitrage met minimale vraagscore en score-deadband.
- [x] Actuele/gewilde/voorgestelde/geblokkeerde modus afzonderlijk zichtbaar.
- [x] Betrouwbare modusfeedback en minimumtijd tussen waargenomen moduswisselingen.
- [x] Eén deadline-timer, geen polling; conservatieve wachtperiode bij restart/reload.
- [x] UI-configuratie, twee compacte typen diagnostische entiteiten en export.
- [x] Additieve compatibiliteit met Zonentra 0.1 zonder nieuwe Config Flow.
- [x] 79 tests, linting, formatting en controles op nul hardwarecommando's.
- [x] Gebruiker heeft 0.2 via HACS bijgewerkt op de kantoorinstallatie.

Zie [ALGORITHM.md](ALGORITHM.md) voor de concrete formules en beperkingen. In deze
versie wordt niets actief geregeld, ook geen off-/uitschakelcommando.

### Versie 0.3 — centrale configuratie (geïmplementeerd)

- [x] VTherm-centralisatie en lokale parameterkeuzes onderzocht.
- [x] Eén buitentemperatuurbron met eigen bronleeftijd voor het gebouw.
- [x] Centrale klimaatgrenzen/entiteiten en meetparameters.
- [x] Twee onafhankelijke keuzes per ruimte om centraal over te nemen of lokaal af te wijken.
- [x] Effectieve profielen en zichtbare herkomst in ruimteattributen.
- [x] Ruimteregelaarkoppeling verwijderd; oude koppelingen automatisch opgeschoond.
- [x] Configuratieversie 3 met behoud van bestaand ruimtebeleid en stabiele IDs.
- [x] Tegenstrijdige oude buitenbronnen vereisen expliciete selectie.
- [x] 92 tests inclusief migratie, UI, timers en nul hardwarecommando's.
- [ ] Publicatie en praktijktest van 0.3 op de kantoorinstallatie.

### Versie 0.3.1 — sensorvalidatie (geïmplementeerd)

- [x] Root cause: rapportleeftijd van 1800 s keurde stabiele KNX-temperaturen af.
- [x] `state_based` (standaard) en optioneel `update_based` via `last_reported`.
- [x] Grensentiteiten verouderen niet meer op leeftijd.
- [x] Diagnostiek: strategie, leeftijden, reden-code en `freshness_verified`.
- [x] Bestaande configuraties zonder strategie werken zonder herconfiguratie.
- [x] Regressietests voor stabiele, ongeldige, onbeschikbare en herstellende bronnen.
- [ ] Praktijkcontrole: een stabiele KNX-temperatuur blijft `valid` na 44+ minuten stabiele waarde.

### Versie 0.4.0 — binnenunitobservatie (geïmplementeerd)

- [x] Binnenunits = bestaande HVAC-apparatuur; geen dubbele configuratie.
- [x] Selected mode, reported action en fysieke modus strikt gescheiden.
- [x] Pure Mode Detection Engine met consensus, activiteit, afgeleide modus en kwaliteit.
- [x] Conflictdetectie en vergelijking met de gewenste modus via reason codes.
- [x] Binnenunit- en afgeleide-groepsmodussensoren, uitgebreide diagnostiek.
- [x] `current_mode_unknown` blijft zonder betrouwbare fysieke feedback gehandhaafd.
- [ ] Praktijkcontrole met de airco's van de kantoorinstallatie.

### Versie 0.5.0 — gesimuleerde regelstrategie (geïmplementeerd)

- [x] Leidende groepsmodus (heat/cool/neutral/unknown) uit de bestaande gewogen vraag.
- [x] Control Intent Engine per binnenunit met reason codes en tussenstappen.
- [x] Manual Override via state-events van de KNX-climate-entiteit (standaard 30 min).
- [x] CommandTracker met begrensde bevestiging voor toekomstige aansturing.
- [x] Anti-pendel (min. aan/uit) en heat↔cool-omschakeling als state machine.
- [x] Simulatiesensoren per binnenunit en per groep; uitgebreide diagnostiek.
- [x] Geen enkele servicecall; `active_switch_permitted` altijd false.
- [ ] Veiligheidswaarden verifiëren met Mitsubishi en praktijkvergelijking met de installatie.

### Versie 0.6.0 — opbouw zoals Versatile Thermostat (geïmplementeerd)

- [x] Eén centrale configuratie (gebouw, groepen, gedeelde instellingen).
- [x] Per ruimte een eigen config entry en apparaat; per item Configureren.
- [x] Pure samenvoeging naar het bestaande gebouwmodel; rekenkern ongewijzigd.
- [x] Validatie: binnenunit in één ruimte, groep bestaat, centrale verplicht.
- [x] Oud enkel item werkt door met reparatiemelding (opnieuw aanmaken).
- [ ] Overstap op de kantoorinstallatie: oud item vervangen door centraal + ruimtes.

### Versie 0.7.0 — actieve standregeling (geïmplementeerd)

- [x] Zonentra zet per buitenunitgroep de stand van alle binnenunits (vervangt de eigen automation).
- [x] Lopende units wisselen mee; units die uit staan krijgen een klaarzet-puls.
- [x] Correctie van units die in de verkeerde stand worden aangezet.
- [x] Noodstop-schakelaar per groep, commandolog en opgeslagen laatste stand.
- [x] Herkomst via HA-context: automations starten geen Manual Override.
- [ ] Afgeleide buitenunitmodus ("eerste aan bepaalt") als extra diagnose.
- [ ] Praktijkperiode: commandolog en gedrag beoordelen vóór verdere aansturing.

### Versie 0.8.0 — aanwezigheid en beweging (geïmplementeerd)

- [x] Aanwezigheid gebouw in de centrale configuratie (meerdere brontypen).
- [x] Bewegingssensor per ruimte met detectie- en nalooptijd, zoals Versatile Thermostat.
- [x] Comfort-, eco- en afwezig-band; aanwezigheid gaat voor beweging.
- [x] 0.9.0: Zonentra-thermostaat per ruimte (zie hieronder).

### Versie 0.9.0 — Zonentra-thermostaat per ruimte (geïmplementeerd)

- [x] Climate-entiteit per ruimte met comfortband, standaardmodi heat/cool/heat_cool/off en presets (comfort, eco, afwezig).
- [x] Comfortband als instellingen op het ruimteapparaat en een sensor Actieve band.
- [x] Schakelaar Ruimteregeling per ruimte, standaard uit; thermostaat bewaard in HA-opslag.
- [x] Ruimteregeling: binnenunits aan/uit op de klimaatvraag, alleen in de stand van de buitenunit.
- [x] Zelfregulerend setpoint op de ruimtesensor, begrensd en met minimale wachttijd.
- [x] Handmatig uit en handmatig setpoint in een geregelde ruimte starten een Manual Override.
- [ ] Praktijkperiode met één ruimte: commandolog, setpointgedrag en comfort beoordelen.
- [x] Ventilatorstand en raamcontacten (raam open → unit uit) in de ruimteregeling (0.10).

### Versie 0.10.0 — ruimtesensoren zoals Versatile Thermostat (geïmplementeerd)

- [x] Sensoren aanwezigheid, veiligheid, raam, geregeld setpoint, gladgestreken temperatuur en temperatuurtrend.
- [x] Raamdetectie met vertraging en bypass-schakelaar; raam open → units direct uit.
- [x] Automatische ventilatorstand op de afstand tot het doel.
- [x] Lamel omhoog bij koelen, omlaag bij verwarmen (select of number).
- [x] Preset `comfort` volgt aanwezigheid en beweging (vervangt `activity`).
- [ ] Energie en overbelasting: alleen met vermogensmeting per airco.

### Vervolg vóór actieve regeling

Inventariseer de fysieke topologie, betrouwbare gatewayfeedback en huidige
schrijvers. Kies expliciet de eigenaar van elke installatie. Verifieer Mitsubishi-
minimumlooptijden, break-before-make, veilige omschakeling en bevestiging/timeouts.
Voeg handmatige override toe. Een eigen room controller volgt alleen bij
aangetoonde behoefte; VTherm-koppeling is uit het plan verwijderd.

Pas na expliciete keuze voor actieve regeling komt één executor met deduplicatie,
rate limits, lifecyclebeleid, overrides en feedback. De 16 °C-vloerverwarmingsgrens
blijft beschermd. De huidige minimumtijd is een read-only analyseguard, geen
gevalideerd actief HVAC-schakelprotocol.

## Fase 3 — gebouwoptimalisatie

Planning, occupied/unoccupied/unknown op gebouw- en ruimteniveau, debounce en
mmWave-uitbreiding. Alarmmapping expliciet configureren. Voeg weercontext en
zonwering toe nadat geveloriëntatie en lokale KNX-veiligheid zijn geverifieerd.
Ventilatie combineert CO₂ en comfort met beperking van warmteverlies. Verwerk
passieve zonweringsvoorstellen in dezelfde arbitrage als HVAC.

Exit: aantoonbaar minder heen-en-weer schakelen; onbekende bezetting krijgt een
conservatieve behandeling; lokale KNX-veiligheid blijft onafhankelijk functioneren.

## Fase 4 — energieoptimalisatie

P1/PV/apparaatmeters, dynamische tarieven, historie en voorspellende modellen.
Buitenunit-kWh-meters zijn optioneel; modelleer meetdekking en onzekerheid expliciet.
Presenteer estimated nooit als measured. Prijsoptimalisatie mag comfort- en
veiligheidsgrenzen niet passeren. Valideer voorspellingen met historische replay
voordat ze actief meewegen.

Exit: meetherkomst zichtbaar, reproduceerbare vergelijking met baseline, lokale
fallback zonder prijs- of weersdata en optionele databronnen zonder cloudverplichting.
