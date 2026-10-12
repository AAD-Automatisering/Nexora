# Zonentra 0.2 — uitlegbare klimaatintelligentie

Alles in dit document betreft **read-only analyse**. Een voorgestelde modus is
geen commando, en verandert ook niet de intern bijgehouden actuele modus.

## Gevalideerde bronnen en ruimtesnapshots

HA-states worden op de eventloop gekopieerd naar immutable `SourceState`-waarden.
De pure kern bouwt daaruit per ruimte een `ZoneSnapshot`: temperatuur, twee
grenzen, optionele vochtigheid/CO₂/buitentemperatuur, aanwezigheid, contacten en
IDs van gekoppelde HVAC-, vloerverwarmings- en zonweringsapparatuur.

`Reading.quality` onderscheidt:

| Quality | Betekenis |
|---|---|
| valid | Waarde, eenheid en ingestelde leeftijd zijn geaccepteerd |
| missing | Bron of vaste grens is niet geconfigureerd/aanwezig |
| unknown | HA meldt expliciet unknown |
| unavailable | HA meldt expliciet unavailable |
| stale | Laatste HA-rapport is minstens zo oud als de ingestelde maximale leeftijd |
| unreliable | Ongeldige waarde, eenheid, timestamp, bereik of restored/assumed status |

Temperaturen met °C en °F worden naar Celsius genormaliseerd. Geen eenheid of een
onbekende eenheid wordt niet geraden. Temperatuurmetingen moeten tussen −50 en
65 °C liggen; analysegrenzen tussen 5 en 35 °C. NaN, infinity en niet-numerieke
waarden zijn ongeldig. Vochtigheid moet 0–100 % zijn en CO₂ 0–10.000 ppm. Deze
bereiken zijn plausibiliteitschecks, geen garantie van sensorcalibratie.

`last_reported` bepaalt leeftijd, **niet last_changed**. Een stabiele waarde die
opnieuw gemeld wordt, blijft dus vers. Standaard is de maximale meetleeftijd
1800 seconden; pas dit aan de werkelijke KNX-/gateway-rapportage aan. Met 0 is
leeftijdcontrole expliciet uitgeschakeld. Een toekomsttimestamp >5 seconden of
ontbrekende/tijdzoneloze timestamp is onbetrouwbaar. Een HA-rapport bewijst niet
dat de fysieke sensor opnieuw gemeten heeft: gecachte gatewaydata blijft een
beperking van deze bronkwaliteit.

Aanwezigheid: on → occupied, off → unoccupied, ontbrekend/ongeldig → unknown.
Contacten: on → open, off → closed. Voor statische binaire toestanden is er geen
leeftijdtimeout; unavailable/unknown/restored/assumed blijven wel ongeldig.
Afwezigheid, open ramen, CO₂, vochtigheid en buitenweer beïnvloeden in 0.2 de
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

## Events en herbeoordeling

Bronveranderingen gebruiken `async_track_state_change_event`. Voor rapporten met
ongewijzigde waarde is er een gefilterde `EVENT_STATE_REPORTED`-listener, zoals de
actuele HA-API voorschrijft. De runtime plant slechts één timer naar de eerstvolgende
sensorvervaldatum of geblokkeerde omschakeldeadline. Er is geen periodieke polling.
Bij unload worden zowel bronlisteners als de timer verwijderd.

De beslisengine importeert geen Home Assistant en heeft geen uitvoerinterface.
Elke fysieke apparatuurvermelding blijft daarnaast een hold-beslissing behouden
in de bestaande Status-sensor, ook als de nieuwe groepssensor een mode voorstelt.
