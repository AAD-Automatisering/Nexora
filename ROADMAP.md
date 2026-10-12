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
- [ ] Publicatie en praktijktest van 0.2 op de kantoorinstallatie.

Zie [ALGORITHM.md](ALGORITHM.md) voor de concrete formules en beperkingen. In deze
versie wordt niets actief geregeld, ook geen off-/uitschakelcommando.

### Vervolg vóór actieve regeling

Inventariseer de fysieke topologie, betrouwbare gatewayfeedback en huidige
schrijvers. Kies expliciet de eigenaar van elke installatie. Verifieer Mitsubishi-
minimumlooptijden, break-before-make, veilige omschakeling en bevestiging/timeouts.
Voeg handmatige override en een publieke room-controlleradapter voor VTherm toe.
Een eigen room controller volgt alleen bij aangetoonde behoefte.

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
