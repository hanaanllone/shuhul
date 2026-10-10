# Shuhul

Shuhul, "shade" in Kashmiri, is a map-first planning tool for Kashmir. It puts
the environment on the same map as a proposed road, bridge or flyover, so that
heat, trees, water and flood risk are weighed before a route is chosen, not
after.

Urban development across South Asia is often driven by infrastructure needs
without giving environmental impact the same weight. Green space shrinks, trees
are removed and water bodies are built over, with little accounting for the
cost. Shuhul is built for the governments and planners who make those choices,
and for places where data is sparse: everything it uses is open data.

Built by team Henz te Gruse (Hanaan Lone and Sayan Qadri) for the WeMakeDevs ×
AWS Environmental Hacks hackathon, on the Heat and Water track, with air
quality in support.

**Live:** https://13-204-178-165.sslip.io

## Contents

- [What you can do with it](#what-you-can-do-with-it)
- [Route planner](#route-planner)
- [Area analysis and what if](#area-analysis-and-what-if)
- [Ecological stress and greening priority](#ecological-stress-and-greening-priority)
- [Where to build](#where-to-build)
- [Air and temperature](#air-and-temperature)
- [Environmental Watch](#environmental-watch)
- [Map layers](#map-layers)
- [Coverage](#coverage)
- [How the estimates are made](#how-the-estimates-are-made)
- [What it does not claim](#what-it-does-not-claim)
- [How it is built](#how-it-is-built)
- [On AWS](#on-aws)
- [API](#api)
- [Running it](#running-it)
- [Building the data](#building-the-data)

## What you can do with it

| Page | What it answers |
| --- | --- |
| Route plan | Which way should a new road go, and what would each way cost the land? |
| Area analysis | What is this area like today, how has it changed, and what if part of it changed? |
| Ecological stress | Where is the land already under pressure, and why? |
| Greening priority | Where would planting do the most good? |
| Where to build | Where could a new building or facility go at the least environmental cost? |
| Air and temperature | How hot and how polluted is it now, and against the past? |
| Watch | What environmental problems are being reported, and where? |

After signing in, **Home** lists your projects. Each card is a small map of
that project's routes. The top bar has Home, Watch, Route plan and Environment
(Area analysis, Ecological stress, Where to build, Air and temperature), and
three icons: profile, settings and sign out.

## Route planner

### Setting up

1. Name the project and choose the **construction type**: road, bridge or
   flyover.
2. Set the **corridor width**, 6 to 60 m: how wide a strip of land the project
   takes.
3. Place **point A** and **point B** on the map. Both have to be in the same
   district.
4. Set the priorities and the land that must never be built on.
5. Press **Plan routes**.

The analysis runs in the background and reports its stage. When a saved
project is open, **Update this project** runs it again in place and **Save as
a new project** keeps the old one and makes another.

### Priorities

Each slider runs from 0 to 100 and has an info mark that says what it does.

| Priority | Moving it higher |
| --- | --- |
| Protect trees | keeps routes away from tree canopy and dense vegetation |
| Protect green space | keeps routes off fields, parks and other green land |
| Protect water | keeps routes away from rivers, lakes and wet ground |
| Avoid adding heat | avoids land that would warm most if paved |
| Avoid flood-prone land | avoids low ground where water has stood before |
| Keep the route short | makes the balanced route more direct and less careful of the land |
| Ease of construction | avoids steep slopes and buildings in the way |

### Never build on

Ticking one of these forbids that land outright. A route goes round it or is
not offered at all.

| Limit | Land forbidden |
| --- | --- |
| Heritage sites | within 100 m of a mapped heritage point |
| Water bodies | rivers, lakes and ponds in the water layer |
| Hill forest | tree canopy 10 m or taller, in patches of 5 ha or more, on slopes averaging 8° or more |
| Recorded flood land | the very high flood class: land where water has been recorded since 1984 |
| Very steep terrain | slopes of 30° or more |

If the limits leave no way through, or a point sits on forbidden land, the
planner says so in plain words.

### Road, bridge and flyover

The three types are routed over the same land with different sensitivities.
A bridge is expected to cross water, so water costs it far less; a flyover
passes over buildings more easily than a road does. The figures below
multiply each factor's cost.

| Factor | Road | Bridge | Flyover |
| --- | --- | --- | --- |
| Water | 1.50 | 0.35 | 0.60 |
| Buildings | 1.25 | 1.10 | 0.70 |
| Heritage | 1.00 | 1.00 | 1.15 |
| Slope | 1.00 | 0.90 | 0.90 |
| Tree canopy | 1.00 | 0.85 | 0.75 |
| Flood | 1.00 | 0.50 | 0.50 |

These are planning-level weights, not engineering or cost models. For heat,
all three are treated as a paved surface the width of the corridor. The
"Water bodies" limit applies to every type, so leave it unticked for a bridge
that has to cross a river.

### Results

Three alternatives are offered. They are alternatives, not a ranking.

| Route | How it is found |
| --- | --- |
| A, shortest | distance only |
| B, balanced | distance against environmental cost, in the share set by "Keep the route short" |
| C, lower environmental impact | 85% environmental cost, 15% distance |

- **Routes** compares them side by side: length, tree-equivalents, green
  space, water crossings, named buildings, heritage sites, mean slope, heat
  added, flood-prone land and a relative environmental cost.
- **Heat and flood** shows, for the selected route, the surface temperature of
  its surroundings today, after building and after mitigation; the heat added
  within 300 m; the share repaid by the mitigation plan; and the flood-prone
  land, recorded water and former water inside the corridor.
- **Mitigation** shows what the route owes and where it can be repaid: canopy
  removed, canopy owed at 2 for 1, area planned, and each zone by type (tree
  planting, shrubs along roads, green roofs). The kinds can be switched on and
  off on the map, and selecting a zone in the table highlights it.
- **Method** lists the weights used for this project.
- **Layers** switches the map layers, the routes, the corridors and the
  mitigation zones.
- **Report** opens a printable page with the routes, figures, method and
  limits.

## Area analysis and what if

Choose a district, or draw an area with the **Rectangle** or **Polygon**
tool. A drawn area can be edited, moved or deleted. Shuhul reports:

- **Heat:** average and hottest-tenth surface temperature, and the modelled
  warming if the land were paved.
- **Green and built:** tree canopy, vegetation index, share under roofs and
  the land cover mix.
- **Water and flood:** water cover, flood-prone share and water lost since
  1984.
- **Change over time:** vegetation, built-up index and temperature for each
  summer from 2017, with the number of clear satellite looks behind each year.

**What if** estimates the change in surface temperature, inside the drawn
area and within 300 m of it, if a share of the suitable land were changed:

| Change | Land it uses |
| --- | --- |
| Plant trees | open land: not water, not built-up, not already under trees |
| Plant shrubs and grass | the same open land |
| Green the roofs | roofs |
| Pave the unbuilt land | land that is not water and not built-up |
| Build on the unbuilt land | the same |

Drawn areas up to 25 km² are accepted, in districts where surface temperature
has been modelled.

## Ecological stress and greening priority

Each district is divided into 500 m zones.

**Stress** scores each zone from 0 to 1 on five indicators and names the ones
that push it up most.

| Indicator | Weight | Stress rises with |
| --- | --- | --- |
| Surface temperature | 25% | hotter ground |
| Vegetation | 25% | less greenness |
| Tree canopy | 20% | less canopy |
| Built-up density | 20% | more roof cover |
| Surface moisture | 10% | drier ground |

Below 0.34 is low, 0.34 to 0.66 moderate, 0.67 and above high.

**Greening priority** ranks the same zones for planting.

| Factor | Weight |
| --- | --- |
| Little tree canopy | 35% |
| Hot surface | 25% |
| Busy roads | 25% |
| Densely built | 15% |

The top 15% of zones are high priority, the next 35% moderate. Zones that are
mostly water are left out. Schools, colleges, hospitals and clinics tagged on
OpenStreetMap are shown in each zone, and a filter keeps only the zones that
have one. The district's fine-particle average for the past year is shown
beside the ranking.

## Where to build

Before a route there is a site. Say how much open land a project needs,
whether it needs a road, and whether to stay off flood-prone land. Shuhul
ranks the 500 m zones where building would cost least.

| Factor | Weight | Better when |
| --- | --- | --- |
| Trees | 25% | less canopy to lose |
| Flood | 25% | less flood-prone land |
| Heat | 20% | less warming if paved |
| Room | 20% | more open land |
| Slope | 10% | gentler ground |

Always left out: zones that are mostly water or wetland, within 100 m of a
heritage site, or 20% or more hill forest. Open land includes farmland;
Shuhul does not know who owns it or what it is used for.

## Air and temperature

For each district: the temperature now, today's range, and how today compares
with the usual high for the month; the average July high for each of the last
ten summers and the hottest day in that time; fine particles (PM2.5) now, the
average for the past year, the days over the national 24-hour standard of
60 µg/m³, and the average for each month.

## Environmental Watch

- **Live reports.** Shuhul reads Greater Kashmir, Free Press Kashmir and
  Kashmir Life, from their feeds and public search, every three hours on the
  server. It keeps the reports on trees, wetlands, flooding, heat, waste,
  air, water, land and construction, sorts them into ten types, and places
  them on the map from the place names in the text. It stores the headline,
  the link, a short excerpt and what it extracted, not the article.
- **Filters.** By type, by district and by words in the headline.
- **Summarise.** A brief of any report: what it is about, where, the figures
  it gives, the public bodies it names and the two lines that carry the most
  of that. It is built from the report's own words by fixed rules, with no
  language model, so nothing in it is invented.
- **What the satellite record shows.** For a report that names a place: how
  vegetation and hard surface have moved within 500 m of it since 2017, with
  its temperature, canopy and flood share. This shows where to look. It does
  not confirm or refute the report.
- **Open in the route planner.** Opens the map at the reported place with the
  layers for that type of issue switched on.
- **Curated archive.** Twenty-two hand-picked reports with the same brief,
  and one worked example of the fuller analysis a language model produces.

## Map layers

| Layer | Shows | Source | Resolution | Confidence |
| --- | --- | --- | --- | --- |
| Surface temperature | Mid-morning summer surface temperature, median of the latest three years | Landsat 8 and 9 Collection 2 | 30 m | Medium |
| Warming if paved | Estimated rise if a cell alone were paved | Shuhul thermal model | 30 m | Low |
| Vegetation | Greenness index (NDVI) | Sentinel-2 composite, May to July | 10 m | High |
| Tree canopy | Canopy height where land cover also shows trees | Canopy height layer with ESA WorldCover 2021 | 10 m | Medium |
| Hill forest | Tall canopy in large patches on slopes | Derived | 10 m | Low |
| Land cover | Eleven classes | ESA WorldCover 2021 | 10 m | Medium |
| Building cover | Share of each cell under a roof | Microsoft detected footprints, OpenStreetMap named buildings | 10 m | Medium |
| Heritage buffer | 100 m around heritage points | OpenStreetMap | 10 m | Low |
| Water | Open water | Satellite water index | 10 m | High |
| Water index | Wetness index (NDWI) | Sentinel-2 composite | 10 m | High |
| Water history | Share of satellite looks with water, 1984 to 2021 | JRC Global Surface Water | 30 m | Medium |
| Lost water | Permanent or seasonal water that has become land | JRC Global Surface Water | 30 m | Medium |
| Flood susceptibility | Four classes of a screening index | Derived | 10 m | Low |
| Slope | Degrees | 30 m elevation model | 30 m | Medium |

The base map is OpenStreetMap in the Humanitarian style. Every layer has its
legend on the map and its source, limits and confidence in the Layers tab.
Everything sits on one 10 m grid per district (UTM zone 43N), and the map
tiles are built ahead of time.

Other data: weather from Open-Meteo (ERA5 reanalysis and a forecast model,
about 10 to 25 km) and air quality from Open-Meteo's CAMS global model (about
40 km); place names from OpenStreetMap Nominatim.

## Coverage

Eleven districts of Kashmir: Srinagar, Srinagar city, Anantnag, Bandipora,
Baramulla, Budgam, Ganderbal, Kulgam, Kupwara, Pulwama and Shopian.

Every district has every layer and every feature. Srinagar and Srinagar city
have a summer composite for each year from 2017 to 2025, so their change over
time runs nine years. The other nine districts have the latest three summers,
2023 to 2025, which is what the surface temperature layer needs; their change
over time is three years long. Where a place lacks the data for something,
the page says "No data".

## How the estimates are made

**Routes** are least-cost paths over a 10 m cost surface. Each cell's
environmental cost is a weighted sum of nine factors. The starting weights
are below; the priorities scale them, and they are then brought back to a
total of 1.

| Factor | Weight | Cost rises with |
| --- | --- | --- |
| Vegetation | 0.20 | greenness |
| Tree canopy | 0.20 | canopy height, up to 30 m |
| Slope | 0.15 | steepness, up to 30° |
| Water | 0.15 | open water |
| Buildings | 0.15 | roof cover |
| Heritage | 0.10 | being inside a heritage buffer |
| Warming if paved | 0.10 | modelled warming, up to 2 °C |
| Flood | 0.10 | flood index, from moderate to very high |
| Existing roads | 0.05 | not following a road that is already there |

**Impact.** Each route is buffered to the corridor width and the layers are
read inside it. Tree-equivalents are canopy area divided by 25 m² a tree.
Green space is land with a vegetation index of 0.30 or more.

**Heat** comes from a gradient-boosted model that predicts summer surface
temperature from vegetation, canopy, roofs, land cover, water, terrain and
the surroundings at two distances. Each district has its own model, trained
on 300,000 of its cells and tested on whole 3 km blocks it never saw. The
typical error (root mean square) and the share of variation explained:

| District | Typical error | Variation explained |
| --- | --- | --- |
| Srinagar, also used for Srinagar city | 2.33 °C | 88% |
| Shopian | 1.65 °C | 79% |
| Kupwara | 1.98 °C | 81% |
| Baramulla | 2.06 °C | 83% |
| Pulwama | 2.27 °C | 87% |
| Budgam | 3.14 °C | 82% |
| Ganderbal | 3.29 °C | 78% |
| Kulgam | 3.36 °C | 74% |
| Bandipora | 4.01 °C | 68% |
| Anantnag | 4.27 °C | 77% |

The models for the mountain districts are weaker: their land runs from valley
floor to snowline, which is harder to predict than a city. The app shows the
error of the model it used beside every heat estimate. A change of surface is
simulated by changing a cell's inputs and predicting again.
Planting takes only open land and leaves buildings standing. Heat added is
reported in degree-hectares: degrees of warming times the area warmed, within
300 m.

**Mitigation** looks near each route for land that could carry tree planting,
roadside shrubs or green roofs. Roofs and built-up land do not count as open
land. The plan starts at 2 m² of green cover for each m² of canopy removed
and grows until the modelled heat is repaid or the nearby zones are used up,
and says which happened.

**Flood** is a screening index: 40% closeness to recorded water, 30% low
ground, 20% height above the nearest water, 10% flatness. Below 0.45 is low,
to 0.65 moderate, to 0.85 high, above that very high. It is not a hydraulic
model.

**Stress, greening priority and where to build** compare zones inside one
district. Stress scales each indicator between the district's 10th and 90th
percentiles. The two rankings use each zone's standing among the district's
zones on each factor.

## What it does not claim

- Surface temperature is not air temperature. It is a mid-morning satellite
  reading of the ground.
- Tree-equivalents are not a tree count.
- A mitigation zone or a building site is land that looks suitable from the
  data. Ownership and permission are not known.
- Air quality is one modelled value per district. Main roads stand in for
  traffic pollution when zones are ranked.
- The water layer comes from a satellite index, which can miss water under
  weed or algae.
- News reports are sorted by keywords, so some are filed under the wrong
  type, and a place taken from the text can be the wrong one.
- Every figure is a screening estimate to guide where to look, and should be
  checked on the ground before it is relied on.

## How it is built

```
frontend/   React and TypeScript, built with Vite; Leaflet maps
backend/    Flask API, a worker for queued analyses, analysis scripts
processed/  one folder of layers and map tiles per district (not in git)
deploy/     container images, compose file and the AWS stack
```

- **Frontend.** One file per page in `frontend/src/pages`, shared parts in
  `frontend/src/components`, design tokens and styles in
  `frontend/src/styles`. Routing is by the address after `#/`.
- **API.** `backend/app.py`. Sessions are signed cookies; every `/api` route
  needs a signed-in user except health, sign-in and map tiles. Sign-in
  attempts are rate limited.
- **Queue.** A project is a row in the database. The worker
  (`python -m backend.worker`) takes the oldest queued project, runs the
  pipeline and writes its files to `outputs/projects/<id>/`. A queued project
  survives a restart. The worker also re-reads the news outlets.
- **Pipeline.** `backend/services/pipeline.py`: cost surface, routes, impact,
  mitigation, heat and flood effects, report.
- **Database.** SQLite for development, PostgreSQL in production, through
  SQLAlchemy.
- **Report analysis with a language model.** The curated archive has an
  agent built with the Strands Agents SDK on Amazon Bedrock. It is switched
  on by setting `SHUHUL_BEDROCK_MODEL_ID`. Without it, reports get the
  rule-based brief.

## On AWS

| Service | Used for |
| --- | --- |
| EC2 | one machine running the database, API, worker and website with Docker Compose, serving HTTPS itself |
| S3 | the processed dataset, each release of the code, and the machine's status reports |
| CloudFormation | `deploy/stack.yaml` creates the machine, its address, its firewall and its role in one command |
| IAM | a role that lets the machine read the bucket and nothing else of the account |
| Systems Manager | shell access to the machine without an open SSH port |
| Budgets | a spending alert |

A release is one upload: `deploy/upload.sh` puts a code archive and any new
data in the bucket, and the machine picks them up within three minutes and
rebuilds. `deploy/README.md` has the steps, the costs and how to take it down.

## API

All routes are under `/api` and return JSON unless noted.

| Route | Does |
| --- | --- |
| `POST /auth/signup`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/session` | accounts and sessions |
| `POST /account/profile`, `POST /account/password` | change name, organisation or password |
| `GET /projects`, `POST /projects` | list projects, start one |
| `GET /projects/<id>`, `PUT /projects/<id>` | open a project, run it again with new settings |
| `GET /projects/<id>/status`, `/corridors`, `/report` | progress, corridor shapes, printable report (HTML) |
| `GET /districts` | districts and what data each has |
| `GET /layers/<district>/manifest`, `GET /tiles/<district>/<layer>/<z>/<x>/<y>.png` | map layers and their tiles (PNG) |
| `POST /area/environment`, `POST /area/what-if`, `POST /area/around` | measure an area, estimate a change, read the surroundings of a point |
| `POST /aoi/analyse` | vegetation and water indices for an area |
| `GET /stress/<district>` | stress and greening priority zones (GeoJSON) |
| `GET /sites/<district>` | zones ranked as places to build (GeoJSON) |
| `GET /climate/<district>` | air and temperature |
| `GET /watch/issues`, `POST /watch/refresh`, `GET /watch/issues/<id>/brief` | live reports, re-read the outlets, brief of one report |
| `GET /environmental-watch/articles`, `/articles/<id>/brief`, `/search` | curated archive |

## Running it

Needs Python 3.12, Node 22 and the processed data in `processed/<district>/`.

```bash
pip install -r requirements.txt
python -m flask --app backend.app run
```

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and create an account. In development the API
uses a local SQLite file and runs analyses itself; settings are described in
`backend/.env.example`.

## Building the data

Each script takes `--district` and writes into `processed/<district>/`.

```bash
python backend/scripts/fetch_open_data.py --district sxr
python backend/scripts/build_landsat_layers.py --district sxr
python backend/scripts/build_static_layers.py --district sxr
python backend/scripts/build_thermal_model.py --district sxr
python backend/scripts/build_map_tiles.py --district sxr
```

`fetch_open_data.py` downloads land cover, water history, building
footprints and Landsat scenes. `build_landsat_layers.py` makes the yearly
summer composites and the surface temperature layer. `build_static_layers.py`
makes land cover, tree canopy, buildings, roads, heritage, hill forest, water
history and the flood index. `build_thermal_model.py` trains the heat model.
`build_map_tiles.py` cuts the map tiles.
