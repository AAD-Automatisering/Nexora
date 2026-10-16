**Review Zonentra 0.13.6 — 15 oktober 2026**

Onderzocht: alle 25 Python-modules van de integratie, configuratie en migratie, entiteiten, actieve aansturing, pure rekenlogica, zonwering, aanwezigheid, weersverwachting, diagnostiek, vertalingen, documentatie en de bestaande tests. Basis: commit `ac8f9f9`; de werkboom was bij aanvang schoon. Tijdens de oorspronkelijke review is de integratiecode niet gewijzigd; de vervolgsecties beschrijven de latere reparaties.

**Vervolg: punt 1 hersteld.** Het uitschakelen van een zone herbouwt nu de centrale regeling zonder die zone; uitgestelde pulscommando’s voor weggevallen apparatuur worden verwijderd. Opnieuw inschakelen herstelt de opgeslagen ruimteregeling en gewone zone-reloads behouden de centrale runtime. Drie nieuwe regressietests toegevoegd; de volledige suite slaagt met 1.054 tests. De onderstaande review beschrijft de oorspronkelijke bevindingen.

**Vervolg: punt 2 hersteld.** Groepspresets worden nu pas opgeslagen nadat alle betreffende modusaanroepen zijn geslaagd. Mislukte units worden na twee minuten opnieuw beoordeeld; geslaagde units worden tijdens dezelfde aanvraag niet opnieuw gepulst. De uitschakelpuls wordt pas na een geslaagd inschakelcommando ingepland en krijgt bij een servicefout ook een herpoging. Openstaande aanvragen blijven bij centrale reloads behouden, ook als een serviceantwoord tijdens setup binnenkomt. Negen nieuwe regressietests; de volledige suite slaagt met 1.063 tests. Dit bevestigt serviceacceptatie, geen fysieke buitenunitfeedback. Lopende gedeeltelijke aanvragen zijn niet op schijf opgeslagen; na een volledige HA-herstart kan een nog niet volledig toegepaste groepspreset opnieuw worden voorbereid.

**Vervolg: punt 3 hersteld.** De groepsschakelaar blokkeert nu alle HVAC- en lamelcommando’s voor de groep, inclusief ruimteregeling, setpoints en ventilatorstanden. Een controle direct voor de serviceaanroep blokkeert ook eerder geplande commando’s. Openstaande presetaanvragen en pulsen worden bij uitschakelen verwijderd; late serviceresponsen starten geen nieuwe puls of herpoging. De ruimte-instellingen blijven bewaard voor opnieuw inschakelen. Zelfstandige ruimtes zonder groep en zonwering met een eigen schakelaar blijven onafhankelijk. Tien regressietests toegevoegd; de volledige suite slaagt met 1.073 tests. Reeds verzonden apparaatcommando’s kunnen hiermee niet worden teruggedraaid.

**Vervolg: punt 4 hersteld.** Het lokale parameterformulier vervangt nu de zichtbare velden in plaats van nieuwe waarden over oude koppelingen heen te leggen. Leegmaken verwijdert daardoor de lokale grensentiteiten uit de configuratie en uit de bronnen van de runtime. Verborgen lokale grensinstellingen en parameters blijven bewaard. Dezelfde afhandeling geldt bij aanmaken, aanpassen en opnieuw indienen na een validatiefout. Vier volledige flow-regressietests toegevoegd; de volledige suite slaagt met 1.074 tests.

**Vervolg: punten 5, 6 en 7 hersteld.** Weersverwachtingen worden met de eenheid van de weerentiteit naar Celsius omgerekend; zonder expliciete eenheid geldt de HA-systeemeenheid. Ongeldige eenheden en niet-eindige waarden worden niet gebruikt voor het dagtype. De setpointplanner rekent in Celsius en zet native stapgroottes als temperatuurverschil om, met behoud van het native afrondingsraster. Uitgaande climate-services volgen de HA-systeemeenheid en worden in de native apparaateenheid afgerond en begrensd. De bevestiging van eigen commando’s houdt rekening met de precisie van HA-states. Alle bronvelden uit BuildingSettings worden nu systematisch geredigeerd; de ruimte-export gebruikt een lijst met geredigeerde equipment_id-velden in plaats van apparaat-ID’s als woordenboeksleutel. Er zijn 22 regressietests toegevoegd, waaronder tien routes via echte HA-climate-services voor gemengde eenheden en grenzen. De volledige suite slaagt met 1.096 tests. Alle zeven genummerde reviewbevindingen zijn hiermee hersteld; de oorspronkelijke bevindingen hieronder blijven als geschiedenis staan.

**Vervolg: overige code- en omgevingspunten opgepakt — 16 oktober 2026.** Onbeschikbare, onbekende en herstelde/aangenomen cover-states blokkeren beweging; terugkeer van de bron start geen handmatige override. Alleen een betrouwbare `off`-state geeft een ingestelde wind-/regenblokkade vrij. De dispatcher controleert dit opnieuw vlak voor verzending. Een mislukte cover-service telt niet als geslaagde beweging en krijgt na twee minuten een herbeoordeling, met behoud van de retry bij centrale reloads. De zonstand-entiteit is nu instelbaar; ontbrekende of ongeldige zonstand geeft een Reparaties-melding die bij herstel of verwijderen van de screens verdwijnt. De drie ongebruikte constanten zijn verwijderd, de coverpositie-interpretatie is gedeeld en zonwering en commando-uitvoering staan in eigen runtime-modules. `ModeCommand.domain` wordt nu door de gedeelde dispatcher gebruikt, ook voor lamellen. De lokale `.venv` werkt met Python 3.14.8 vanuit een eigen runtime onder `.venv`, zonder tijdelijke interpreterverwijzing. Validatie: **1.131 tests geslaagd**, inclusief 30 nieuwe bronherstel-/blokkadegevallen en één volledige configuratieflow voor een alternatieve zonentiteit; daarnaast slagen alle negen reviewprobes en Ruff. Alleen de praktijktest en afstemming met echte apparatuur blijven open.

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

**Ongebruikte code en onderhoud — bijgewerkt 16 oktober**

- Verwijderd: `const.VERSION`, `forecast.DAY_TYPES` en `shading.TARGETS`. De releaseversie staat in manifest en pyproject.
- `control.PHASES` en `roomstate.WINDOW_STATES` worden door tests gebruikt om de sensoropties te vergelijken; behouden.
- Legacy-configuratie, `decision.py`, `control.py` en de override-tracker worden nog aangeroepen en blijven behouden.
- Ruff vindt geen ongebruikte imports of ongedefinieerde namen.
- Beschrijvingen van actieve aansturing en pure plannen zijn bijgewerkt. Historische `read_only`-statusvelden blijven compatibel en beschrijven de observatielaag.
- `runtime_shading.py` bevat screenobservatie, blokkades, herstel en de zonstandmelding. `runtime_commands.py` bevat service-uitvoering, de laatste blokkadecontrole en commandolog. Beide delen via mixins de bestaande lifecycle en het geheugen van `BuildingRuntime`; gedeelde bevestigings-/eventhelpers staan in `runtime_helpers.py`.
- `observations.cover_position()` wordt gebruikt door regeling en diagnostiek; de dubbele coverpositie-interpreter is verwijderd.
- `ModeCommand.domain` bepaalt nu bij `_execute()` het HA-servicedomein; lamellen gebruiken ook deze dispatcher. Coverbewegingen houden hun eigen bevestigings- en retrygeheugen.

**Zonwering en eerdere vraag over sun.sun — bijgewerkt 16 oktober**

`sun_entity` wordt gebruikt voor actuele azimut en elevatie, standaard via `sun.sun`. Het veld is instelbaar in de centrale zonweringssectie. Bij screens zonder geldige zonstand blijft het besluit `sun_unknown` en toont Reparaties een melding. Herstel wist die melding. Er is bewust geen verplichte Sun-dependency voor installaties zonder screens; de melding geeft aan hoe de bron te herstellen.

De forecast gebruikt temperatuur voor het dagtype. Toekomstige zonstanden en bewolking worden niet gecombineerd tot een instralingsvoorspelling; dat is een mogelijke uitbreiding, geen onopgeloste reviewfout.

De cover-robuustheidsprobe controleert nu dat een onbeschikbare cover geen commando krijgt. Een ingestelde wind-/regenbron staat alleen bij een betrouwbare `off` beweging toe. Ontbrekende, onbekende, onbeschikbare, herstelde en aangenomen states blokkeren. Herstel wordt via bron-events opnieuw beoordeeld. KNX blijft verantwoordelijk voor de fysieke wind-/regenbeveiliging.

**Nog open**

Praktijktest met de echte KNX/Intesis-apparatuur, covers en weersprovider, inclusief afstemmen van zonvermogendrempel, vertragingen en screenpositie. De geautomatiseerde tests bewijzen de planning, lifecycle en HA-serviceafhandeling; ze bewijzen geen fysieke uitvoering door apparaten.

**Validatie en reproduceerbaarheid**

- Bestaande testset: **1.051 passed in 9,97 s**.
- Ruff lint: geslaagd. Ruff format: alle 59 oorspronkelijke Python-bestanden correct geformatteerd.
- [review_probes.py](/Users/pauldeelen/Documents/GitHub/Zonentra/tests/review_probes.py): negen gerichte probes die inmiddels het herstelde gedrag controleren, inclusief het blokkeren van een onbeschikbare cover. De controle op werkende lokale entiteitgrenzen is behouden.
- De oorspronkelijke probes legden fouten vast. Hun verwachtingen zijn bij reparatie omgedraaid; ze toetsen nu het gewenste gedrag.
- Uitvoeren met een werkende projectomgeving: `python -m pytest -q tests/review_probes.py`. De bestaande suite blijft `python -m pytest -q`.
- De oorspronkelijke `.venv/bin/python` verwees naar een verdwenen tijdelijke interpreter. Op 16 oktober is de omgeving hersteld met een eigen Python 3.14.8-runtime onder de genegeerde `.venv`-map. Tests draaien nu rechtstreeks via `.venv/bin/python -m pytest -q`; een afzonderlijke `PYTHONPATH` is niet nodig. De README beschrijft het aanmaken van een nieuwe omgeving met een interpreter op een vaste locatie.
- Geen fysieke apparaten aangestuurd en geen productie-HA onderzocht. De integratiecode is in de vervolgstappen wel aangepast. Serviceaanroepen in de tests worden gesimuleerd. De review kan geen werking van echte KNX/Intesis-apparaten of weersproviders aantonen.
