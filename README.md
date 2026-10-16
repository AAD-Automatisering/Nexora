# Zonentra

Lokale klimaatregeling voor één gebouw met meerdere ruimtes, als Home Assistant
Custom Integration. Zonentra gebruikt bestaande entiteiten om klimaatvraag te
berekenen en airco's, ventilatoren, lamellen en zonwering te coördineren.
Aanwezigheid, raamcontacten, weersverwachtingen en ruimteagenda's kunnen de
regeling beïnvloeden. Vloerverwarming en gebouwventilatie worden alleen geobserveerd.

## Installatie

Vereist Home Assistant **2026.10.1** of nieuwer; getest met 2026.10.1.
Geen aanvullende runtime-dependencies, YAML of Versatile Thermostat nodig.

1. Open **HACS → Aangepaste repositories** en voeg
   `https://github.com/AAD-Automatisering/Zonentra` toe als **Integration**.
2. Download Zonentra en herstart Home Assistant.
3. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen → Zonentra**.
4. Kies eenmalig **Centrale configuratie** en stel het gebouw en de
   buitentemperatuursensor in.
5. Open **Configureren** bij de centrale configuratie en voeg buitenunitgroepen toe.
6. Voeg Zonentra opnieuw toe voor elke **Ruimte** en koppel de temperatuursensor,
   bestaande climate-entiteiten en hun buitenunitgroep.

Handmatig installeren kan ook: kopieer alleen `custom_components/zonentra` naar
`<Home Assistant config>/custom_components/zonentra` en herstart Home Assistant.

## Eerste gebruik

**Actieve standregeling staat per buitenunitgroep standaard aan.** Daarmee kan
Zonentra direct HVAC- en lamelcommando's versturen. Zet deze schakelaar uit
voordat je binnenunits koppelt als je eerst alleen wilt observeren. Uitgeschakeld
blokkeert hij alle HVAC- en lamelcommando's voor de groep; plannen blijven zichtbaar.

**Ruimteregeling** en **Zonweringregeling** staan per ruimte standaard uit.
Controleer eerst de sensoren en schakel daarna de gewenste regeling per ruimte in.
Zonwering heeft een eigen schakelaar en wordt niet door de HVAC-groepsstop geblokkeerd.
Laat geen andere regeling dezelfde apparaten tegelijk aansturen.

Koppel elke binnenunit aan één ruimte en aan de werkelijke buitenunitgroep.
Controleer minimale aan-/uittijden en omschakelvertragingen voor je apparatuur;
Home Assistant-states bevestigen geen fysieke compressorstand.

## Instellingen en bediening

Via **Configureren** bij de centrale configuratie stel je aanwezigheid,
ruimteregeling, zonwering, weersverwachting, afspraakvoorbereiding en groepen in.
Ruimtes nemen standaard centrale instellingen over en kunnen daarvan afwijken.
Comfortgrenzen stel je in op het centrale apparaat of het ruimteapparaat.

| Functie | Gebruik |
|---|---|
| Thermostaat | Per ruimte temperatuur, modus en eventueel ventilator kiezen |
| Aanwezigheid | Gebouwaanwezigheid en ruimtebeweging kiezen comfort, eco of afwezig |
| Raamcontact | Een open raam stopt ruimteregeling na de ingestelde vertraging |
| Ventilator | Automatisch bij ingeschakelde ruimteregeling; per ruimte uit te zetten |
| Lamellen | Optionele entiteit met standen voor verwarmen en koelen |
| Zonwering | Koppel covers met positie en gevel; stel centraal zonvermogen, zonstand en eventueel een blokkering in |
| Weersverwachting | Koppel centraal een weerentiteit met uurverwachtingen |
| Ruimteagenda | Koppel per ruimte een calendar-entiteit voor adaptieve comfortvoorbereiding |

Standaard is comfort 21–24 °C, eco 19–26 °C en afwezig 16–30 °C.
Handmatige bediening krijgt standaard 30 minuten voorrang. Automatische
ventilatorregeling volgt daarna weer; de schakelaar **Automatische ventilator**
laat de ventilatorkeuze volledig aan de gebruiker wanneer hij uit staat.

Agenda's gebruiken de comfortband en geleerde opwarm-/afkoeltempo's per ruimte.
Stel marge en maximale voorbereiding centraal in via **Afspraakvoorbereiding**;
ruimtes kunnen eigen waarden gebruiken. Een agenda schakelt een uitgeschakelde
thermostaat, ruimteregeling of groepsstop niet in.

## Bijwerken

Werk bij via HACS, herstart Home Assistant en herlaad de browser.

- **0.13.6 / HomeKit:** reset bestaande Zonentra-thermostaten eenmalig met
  `homekit.reset_accessory` zodat modi en ventilatorfuncties opnieuw worden ingelezen.
  Dit is ook nodig wanneer je de automatische ventilatorfunctie wijzigt.
- **Vóór 0.7:** houd rekening met de standaard ingeschakelde actieve standregeling;
  zet bestaande automations voor de groepsmodus uit voordat Zonentra die overneemt.
- **Vóór 0.6:** een oud enkel configuratie-item blijft alleen simuleren. Noteer de
  instellingen, vervang het door een centrale configuratie met aparte ruimtes en
  pas verwijzingen naar gewijzigde entity-ID's aan.

## Diagnostiek en privacy

De sensoren tonen klimaatvraag, plannen, blokkades en commandobevestigingen.
Download diagnostiek via het integratiemenu; namen, identifiers en bronkoppelingen
worden geredigeerd. Controleer exports en logs altijd voordat je ze openbaar deelt.
Configuratie en geleerde gegevens blijven in je eigen Home Assistant-installatie.

Commit geen Home Assistant-configuratie, agenda-exports, diagnostiek, logs,
inloggegevens of lokale editor-/agentinstellingen. De `.gitignore` sluit gangbare
lokale bestanden uit; gebruik uitsluitend fictieve gegevens in voorbeelden en tests.

## Ontwikkelen

Gebruik Python **3.14.2** of nieuwer:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

De repository bevat de integratie, regressietests en CI. Zie
[ALGORITHM.md](ALGORITHM.md) voor beslisregels en
[ARCHITECTURE.md](ARCHITECTURE.md) voor de technische opbouw.
Licentie: [MIT](LICENSE).
