**Review Zonentra 0.13.6 — 15 oktober 2026**

Onderzocht: alle 25 Python-modules van de integratie, configuratie en migratie, entiteiten, actieve aansturing, pure rekenlogica, zonwering, aanwezigheid, weersverwachting, diagnostiek, vertalingen, documentatie en de bestaande tests. Basis: commit `ac8f9f9`; de werkboom was bij aanvang schoon. De integratiecode is niet gewijzigd.

**Vervolg: punt 1 hersteld.** Het uitschakelen van een zone herbouwt nu de centrale regeling zonder die zone; uitgestelde pulscommando’s voor weggevallen apparatuur worden verwijderd. Opnieuw inschakelen herstelt de opgeslagen ruimteregeling en gewone zone-reloads behouden de centrale runtime. Drie nieuwe regressietests toegevoegd; de volledige suite slaagt met 1.054 tests. De onderstaande review beschrijft de oorspronkelijke bevindingen.

**Vervolg: punt 2 hersteld.** Groepspresets worden nu pas opgeslagen nadat alle betreffende modusaanroepen zijn geslaagd. Mislukte units worden na twee minuten opnieuw beoordeeld; geslaagde units worden tijdens dezelfde aanvraag niet opnieuw gepulst. De uitschakelpuls wordt pas na een geslaagd inschakelcommando ingepland en krijgt bij een servicefout ook een herpoging. Openstaande aanvragen blijven bij centrale reloads behouden, ook als een serviceantwoord tijdens setup binnenkomt. Negen nieuwe regressietests; de volledige suite slaagt met 1.063 tests. Dit bevestigt serviceacceptatie, geen fysieke buitenunitfeedback. Lopende gedeeltelijke aanvragen zijn niet op schijf opgeslagen; na een volledige HA-herstart kan een nog niet volledig toegepaste groepspreset opnieuw worden voorbereid.

**Vervolg: punt 3 hersteld.** De groepsschakelaar blokkeert nu alle HVAC- en lamelcommando’s voor de groep, inclusief ruimteregeling, setpoints en ventilatorstanden. Een controle direct voor de serviceaanroep blokkeert ook eerder geplande commando’s. Openstaande presetaanvragen en pulsen worden bij uitschakelen verwijderd; late serviceresponsen starten geen nieuwe puls of herpoging. De ruimte-instellingen blijven bewaard voor opnieuw inschakelen. Zelfstandige ruimtes zonder groep en zonwering met een eigen schakelaar blijven onafhankelijk. Tien regressietests toegevoegd; de volledige suite slaagt met 1.073 tests. Reeds verzonden apparaatcommando’s kunnen hiermee niet worden teruggedraaid.

**Vervolg: punt 4 hersteld.** Het lokale parameterformulier vervangt nu de zichtbare velden in plaats van nieuwe waarden over oude koppelingen heen te leggen. Leegmaken verwijdert daardoor de lokale grensentiteiten uit de configuratie en uit de bronnen van de runtime. Verborgen lokale grensinstellingen en parameters blijven bewaard. Dezelfde afhandeling geldt bij aanmaken, aanpassen en opnieuw indienen na een validatiefout. Vier volledige flow-regressietests toegevoegd; de volledige suite slaagt met 1.074 tests.

**Bevestigde bevindingen, in volgorde van belang**

1. **[P1] Een uitgeschakelde zone blijft fysieke apparatuur aansturen.**

   Locatie: [__init__.py:260](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/__init__.py:260).

   Bij het uitschakelen van de zone-entry verwijdert Home Assistant de zone-entiteiten, maar de centrale runtime behoudt de zone, de temperatuurluisteraar en de ingeschakelde ruimteregeling. `async_unload_entry()` synchroniseert alleen centrale entries; voor het uitschakelen van een zone volgt geen centrale herbouw. `zone_entries()` filtert uitgeschakelde entries wel, maar wordt pas bij zo'n herbouw opnieuw gebruikt.

   Reproductie: zet Ruimteregeling aan, schakel de zone-entry uit en wijzig daarna de temperatuursensor. Er wordt nog steeds `climate.set_hvac_mode(heat)` voor die zone verstuurd. Dit is dus meer dan een achtergebleven weergave.

   Herstel: laat de centrale runtime bij daadwerkelijk uitschakelen van een zone opnieuw samenstellen en stop de aansturing voor die zone onmiddellijk. Houd dit apart van een gewone reload, zodat die geen onnodige herlaadlus veroorzaakt.

2. **[P2] Een mislukt presetcommando wordt blijvend als toegepast behandeld.**

   Locaties: [runtime.py:1297](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/runtime.py:1297), [executor.py:143](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/executor.py:143).

   De groepspreset wordt opgeslagen voordat de serviceaanroep slaagt. `_call()` zet bij een fout alleen de logregel op `failed`; de opgeslagen preset blijft staan. De correctielus slaat uitgeschakelde units vervolgens over. Bij uitgeschakelde ruimteregeling wordt de mislukte voorbereiding daardoor niet opnieuw uitgevoerd zolang de groepsmodus gelijk blijft, ook niet na een herstart die deze preset herstelt.

   Reproductie: laat het eerste `set_hvac_mode` een `HomeAssistantError` geven terwijl de unit uit staat. De preset wordt toch `heat`. Ook na twintig minuten en een expliciete refresh wordt niets opnieuw verstuurd en heet de status `in_sync`.

   Herstel: maak onderscheid tussen gewenst, verzonden en bevestigd; registreer een preset per unit pas na succes/bevestiging en plan begrensde retries. Dezelfde voortijdige registratie verdient aandacht bij `fan_applied` en `vane_applied`; die laatste twee foutpaden zijn hier niet afzonderlijk gereproduceerd.

3. **[P2] De groepsschakelaar is geen noodstop voor alle groepscommando's, terwijl hij zo beschreven wordt.**

   Locaties: [runtime.py:1242](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/runtime.py:1242), [runtime.py:1335](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/runtime.py:1335), [switch.py:1](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/switch.py:1).

   De beschrijving belooft dat uitschakelen ieder groepscommando stopt. In werkelijkheid stopt het de standregeling en openstaande presetpulsen; `_regulate()` blijft actief op basis van de afzonderlijke ruimteschakelaar. Dat pad kan de airco nog aanzetten en setpoints/ventilatorstanden versturen. Ook `_vanes()` wordt nog aangeroepen.

   Reproductie: zet Actieve standregeling uit, zet Ruimteregeling aan en houd warmtevraag. Er volgt alsnog een `set_hvac_mode(heat)`.

   Dit is een bevestigde contract-/documentatiefout; de code ondersteunt kennelijk ook ruimteregeling zonder actieve standregeling. Bepaal daarom expliciet de bedoelde scope: behoud onafhankelijke schakelaars en verwijder de noodstopbelofte, of implementeer de beloofde blokkade centraal voor alle betreffende uitvoerpaden.

4. **[P2] Leegmaken van lokale grensentiteiten verwijdert de bestaande koppeling niet.**

   Locatie: [config_flow.py:491](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/config_flow.py:491).

   `merge_zone()` bewaart eerdere lokale grensinstellingen. In de vervolgstap worden nieuwe waarden met `clean(user_input)` eroverheen gelegd. Lege of ontbrekende velden verdwijnen uit die invoer, waardoor de oude `heating_limit_entity` en `cooling_limit_entity` blijven bestaan. Een gebruiker kan beide velden dus leegmaken zonder dat de koppeling werkelijk verdwijnt.

   Reproductie: begin met twee lokale input_number-koppelingen, doorloop de samenvoeging van het zoneformulier en dien beide parametervelden leeg in. Beide oude entiteiten staan nog in het opgeslagen kandidaat-record.

   Herstel: vervang de velden van het zichtbare parameterblok als geheel. Bewaar alleen instellingen van verborgen/dormante blokken. Voeg naast deze logische reproductie een volledige options-flow-regressietest toe.

5. **[P2] Een weersverwachting in Fahrenheit wordt als Celsius beoordeeld.**

   Locaties: [runtime.py:557](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/runtime.py:557), [forecast.py:65](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/forecast.py:65).

   De responsewaarden worden direct met de Celsius-drempels vergeleken. De `temperature_unit` van de weerentiteit wordt niet gelezen. Home Assistant kan forecasts in de gekozen eenheid van de weerentiteit aanbieden; dat is ook gecontroleerd in de lokaal geïnstalleerde WeatherEntity-implementatie.

   Reproductie: weerentiteit met `temperature_unit: °F`, uurtemperaturen 41 en 50. Dat is maximaal 10 °C en hoort met de standaarddrempels een koude dag te zijn. Zonentra slaat 50 op en kiest `warm`. Dit beïnvloedt zowel zonwering als uitgestelde klimaatvraag.

   Herstel: normaliseer de verwachting naar Celsius bij inlezen en keur onbekende eenheden af. Controleer daarbij ook eindige waarden; `NaN`/oneindig worden nu niet afgewezen.

6. **[P2] De setpointregeling mengt Fahrenheit-attributen met interne Celsius-waarden.**

   Locaties: [runtime.py:1205](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/runtime.py:1205), [runtime.py:1343](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/runtime.py:1343).

   Ruimtesensoren worden naar Celsius omgerekend, maar `temperature`, `min_temp`, `max_temp` en de stapgrootte van climate-states worden ongewijzigd doorgegeven aan de Celsius-setpointplanner. De serviceaanroep krijgt de interne waarde eveneens zonder omzetting; Home Assistant interpreteert service-temperaturen in de ingestelde systeemeenheid. Dit is gecontroleerd in de lokaal geïnstalleerde climate-servicecode.

   Reproductie met Fahrenheit als systeemeenheid: een airco met huidig setpoint 68 °F, bereik 60–86 °F en ruimtetemperatuur 20 °C. De verwarmingsbasis is 22,3 °C, maar de planner klemt zijn resultaat op het numerieke minimum 60. De service zou dat vervolgens als 60 °F interpreteren.

   Herstel: reken alle absolute climate-temperaturen intern om naar Celsius, stapgroottes als temperatuurverschil, en converteer bij service-uitvoer naar de HA-systeemeenheid. Gebruik dezelfde normalisatie voor commandobevestiging.

7. **[P2] Nieuwe bronentiteiten ontbreken in de anonimisering van diagnostiek.**

   Locatie: [diagnostics.py:13](/Users/pauldeelen/Documents/GitHub/Zonentra/custom_components/zonentra/diagnostics.py:13).

   `presence_entity`, `sun_power_entity`, `screen_block_entity` en `weather_entity` ontbreken in `REDACT`. De configuratie wordt volledig in de diagnostiek opgenomen, zodat die entity-ID's leesbaar blijven. Namen van bijvoorbeeld een alarmpaneel kunnen daardoor in een gedeeld diagnosebestand terechtkomen, terwijl oudere bronvelden wel worden geredigeerd.

   Reproductie: configureer `alarm_control_panel.private_office` en `weather.private_address`; beide strings staan ongewijzigd in het geretourneerde diagnoseobject.

   Herstel: voeg alle bronvelden toe aan de redactielijst en toets bronvelden systematisch tegen het model. Zone-diagnostiek bevat daarnaast apparaat-ID's als dictsleutel bij `room_regulation`; beoordeel die ook bij dezelfde opschoning.

**Ongebruikte code en onderhoud**

- Werkelijk zonder gevonden referenties in integratie én tests: `const.VERSION` (staat bovendien nog op 0.11.0), `forecast.DAY_TYPES` en `shading.TARGETS`. Verwijder ze of maak ze de centrale bron voor de bijbehorende opties; de werkelijke releaseversie staat nu in manifest en pyproject.
- `control.PHASES` en `roomstate.WINDOW_STATES` worden alleen door tests gebruikt om de sensoropties te vergelijken. Dat zijn dus geen volledig ongebruikte symbolen. Eventueel kan de productcode deze lijsten ook direct gebruiken.
- De legacy-configuratie, `decision.py`, `control.py` en de override-tracker worden nog aangeroepen. Verwijderen op basis van oude versienummers of het woord 'simulation' zou functionaliteit of compatibiliteit breken.
- Er zijn geen ongebruikte imports of ongedefinieerde namen gevonden door Ruff.
- Opgeschoond: module-/classdocstrings, projectbeschrijving, README, architectuur, algoritme, roadmap en configuratiehulp beschrijven nu de actieve aansturing en de rol van pure plannen. Legacy-configuratie en historische fases zijn expliciet afgebakend. De bestaande `read_only`-statusvelden blijven compatibel en worden als aanduidingen van de observatielaag toegelicht. De oude algemene uitspraak over automations die een override starten is vervangen door de contextafhankelijke herkenning.
- De centrale uitvoer-, lifecycle-, opslag- en waarnemingslogica zit grotendeels in één runtime-module van 1.578 regels. Opsplitsen per regeling is een onderhoudsverbetering; begin met de bevestigde fouten en gedeelde commandobevestiging, zodat de opsplitsing geen bestaande divergentie vastlegt.
- `_cover_position()` en `_screen_position()` dupliceren vrijwel dezelfde interpretatie van coverposities.
- `ModeCommand.domain` wordt gevuld maar stuurt `_execute()` niet aan; cover- en lamelcommando's lopen via aparte `_call()`-paden. Dat veld is momenteel beschrijvend/inert, geen betrouwbare generieke uitvoerinterface.

**Zonwering en eerdere vraag over sun.sun**

`sun_entity` is geen dode instelling: standaard `sun.sun`, gevolgd als bron zodra er screens zijn, en gebruikt voor actuele azimut en elevatie. Een selectieveld ontbreekt en het manifest declareert geen Sun-dependency. Bij ontbrekende zonstand ontstaat `sun_unknown`; overweeg een duidelijke configuratiecontrole of melding als screens worden toegevoegd. De forecast voorspelt temperaturen voor de komende twaalf uur; toekomstige zonstanden en bewolking worden niet in een instralingsvoorspelling gecombineerd.

Een extra probe bevestigt dat ook bij een cover-state `unavailable` een verplaatsingscommando kan worden verstuurd. Dit staat hier als robuustheidspunt, niet als afzonderlijke bewezen bewegingsfout: de onderliggende cover-integratie bepaalt de afhandeling. Controleer beschikbaarheid voordat een beweging als verzonden wordt bijgehouden en plan expliciet hoe na herstel opnieuw beoordeeld wordt. Voor de wind-/regenblokkade geldt nu alleen state `on` als blokkade; gedrag bij onbekende blokkade is een nog expliciet te kiezen beleid.

**Validatie en reproduceerbaarheid**

- Bestaande testset: **1.051 passed in 9,97 s**.
- Ruff lint: geslaagd. Ruff format: alle 59 oorspronkelijke Python-bestanden correct geformatteerd.
- [review_probes.py](/Users/pauldeelen/Documents/GitHub/Zonentra/tests/review_probes.py): negen gerichte probes. Na herstel van punten 1 tot en met 4 controleren de betreffende probes het juiste gedrag; de andere probes bevestigen drie resterende bevindingen, het cover-robuustheidspunt en één negatieve controle: lokale entiteitgrenzen werken bij nieuwe configuratie wel correct.
- De probes toetsen bewust de waargenomen huidige werking, ook waar die fout is. Dat ze slagen betekent dat de reviewbevinding is gereproduceerd; dit zijn geen regressietests die goed gedrag afdwingen. Bij reparatie moeten de relevante verwachtingen worden omgedraaid.
- Uitvoeren met een werkende projectomgeving: `python -m pytest -q tests/review_probes.py`. De bestaande suite blijft `python -m pytest -q`.
- De oorspronkelijke `.venv/bin/python` verwijst naar een verdwenen `/private/tmp/nexora-python`-installatie. Voor deze review is Python 3.14.8 tijdelijk onder `/private/tmp/zonentra-review-python` geïnstalleerd en zijn de bestaande site-packages via `PYTHONPATH` gebruikt. De projectomgeving is niet aangepast.
- Geen fysieke apparaten aangestuurd, geen productie-HA onderzocht en geen wijzigingen aan de integratiecode aangebracht. Serviceaanroepen in de tests zijn mocks. De review kan geen werking van echte KNX/Intesis-apparaten of weersproviders aantonen.
