# Nexora — roadmap

Scope: één Home Assistant-installatie, één Nexora, één gebouw. Alle fases moeten
kleine, onafhankelijk toetsbare stappen blijven. Deze basis doet geen automatische
hardware-aansturing.

## Fase 1 — fundament (deze versie)

- [x] Architectuur en VTherm-referentie/licentieonderzoek.
- [x] Native Custom Integration met Config Flow, één gebouw en Options Flow.
- [x] Zones, sensor-/controllerkoppelingen, apparatuur en buitenunitgroepen.
- [x] Validatie van IDs, verwijzingen, domeinen en dubbele fysieke apparatuur.
- [x] Eventgedreven observatie, diagnostische status en geredigeerde export.
- [x] Pure hold-simulatie en detectie van waargenomen groepsconflicten.
- [x] Tests met echte HA-flow- en lifecycle-helpers; CI-configuratie.
- [ ] Installatie-/UI-smoketest op de werkelijke Home Assistant-installatie.

Exit: alle tests slagen; gebouw is via UI configureerbaar; geen servicecall vanuit
Nexora; herladen ruimt listeners op. De praktijktest blijft een aparte installatie-
verificatie: unit/integratietests vervangen geen echte KNX/Mitsubishi-omgeving.

## Fase 2 — klimaatcoördinatie

1. Inventariseer fysieke topologie en huidige schrijvers; kies expliciete eigenaar
   van elke installatie. Leg beschermde vloerverwarmingsgrens vast.
2. Voeg genormaliseerde temperatuur en bronkwaliteit/freshness toe. Modelleer
   overrides, warmtevraag, koelvraag en comfortbanden als pure functies.
3. Implementeer arbitrage per buitenunitgroep met hysterese, minimumlooptijden,
   omschakelvertragingen en verklaarde weigeringen. Begin in simulatiemodus.
4. Ontwerp een room-controller adapter voor VTherm via publieke interfaces; bouw
   een eigen controller alleen als dat aantoonbaar nodig is.
5. Voeg na expliciete keuze voor actieve regeling één executor toe met feedback,
   deduplicatie, rate limits, timeouts, restartbeleid en veilige handmatige override.

Exit: conflict-, timeout-, sensorstoring-, handmatige override- en herstarttests;
gedocumenteerde Mitsubishi-omschakelvoorwaarden; praktijktest met gecontroleerde
activering. Geen automatische wijziging van de 16 °C-vloerverwarmingsgrens.

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
