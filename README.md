# Shuhul

Shuhul is a map-first planning tool for Kashmir. It puts the environment on
the same map as a proposed road, bridge or flyover, so that heat, trees, water
and flood risk are weighed before a route is chosen, not after.

Urban development across South Asia is often driven by infrastructure needs
without giving environmental impact the same weight. Green space shrinks, trees
are removed and water bodies are built over, with little accounting for the
cost. Shuhul is built for the governments and planners who make those choices,
and for places where data is sparse: everything it uses is open data.

Built for the WeMakeDevs × AWS Environmental Hacks hackathon, on the heat and
water track with air quality in support.

## What it does

**Route planner.** Pick two points. Shuhul proposes three alternatives: the
shortest, a balanced route and one that follows the lowest environmental cost.
Each is scored for trees and green space removed, water crossings, buildings
and heritage sites met, slope, heat added and flood-prone land crossed. The
planner sets how much each concern weighs and what must never be built on.

**Heat.** A thermal model estimates the summer surface temperature of the land
around each route today, after construction and after mitigation, and reports
the heat added within 300 m.

**Mitigation.** For each route Shuhul looks for land nearby that could carry
tree planting, roadside shrubs or green roofs. It starts at two units of green
cover for each unit of tree canopy removed and grows the plan until the added
heat is repaid or suitable land nearby runs out. It says which.

**Area analysis.** Draw any shape, or take a whole district, and read its
surface temperature, tree canopy, land cover, roof cover, flood-prone share,
lost water and how vegetation and built-up land have changed since 2017.
Then ask what if: plant trees on half the open land, green the roofs or pave
what is left, and see the estimated change in surface temperature inside the
area and around it.

**Ecological stress and greening priority.** Each district is divided into
500 m zones scored for existing stress, with the reasons shown. The same zones
are ranked for planting: little canopy, a hot surface, busy roads and dense
building push a zone up the list.

**Where to build.** Before a route there is a site. Say how much open land a
project needs and Shuhul ranks the zones where building would cost least: few
trees to lose, little flood risk, little heat added, gentle ground and a road
to reach it. Heritage buffers, hill forest and water are always left out.

**Air and temperature.** Current conditions against the usual for the month,
ten summers of July temperatures, and a year of fine-particle levels with the
days over the national standard.

**Environmental Watch.** Reads Greater Kashmir, Free Press Kashmir and Kashmir
Life every few hours, keeps the environmental reports, sorts them by type and
places them on the map. A report opens in the planner at the place it names,
with the relevant layers switched on. It can also be set beside the
satellite record: how vegetation and hard surface have moved within 500 m of
that place since 2017. That shows where to look; it does not confirm or
refute the report.

**Report.** Every project has a printable report with its routes, figures,
method and limits.

## Coverage

Srinagar district and Srinagar city have every layer. The nine other Kashmir
districts have the base layers: vegetation, water, elevation, slope and tree
height.

## Data

| Layer | Source | Resolution |
| --- | --- | --- |
| Surface temperature, yearly change | Landsat 8 and 9 Collection 2, June to August, 2017 to 2025 | 30 m |
| Vegetation | Sentinel-2 composite, May to July | 10 m |
| Land cover | ESA WorldCover 2021 | 10 m |
| Tree canopy | Canopy height, kept where WorldCover also shows trees | 10 m |
| Water history, lost water | JRC Global Surface Water, 1984 to 2021 | 30 m |
| Buildings | Microsoft detected footprints, OpenStreetMap named buildings | vector |
| Roads, heritage points | OpenStreetMap | vector |
| Weather | Open-Meteo: ERA5 reanalysis and forecast model | about 10 to 25 km |
| Air quality | Open-Meteo: CAMS global model | about 40 km |
| News | Greater Kashmir, Free Press Kashmir, Kashmir Life | linked, not copied |
| Base map | OpenStreetMap, Humanitarian style | |

Everything is put on one 10 m grid per district (UTM zone 43N).

## How the estimates are made

- **Routes** are least-cost paths over a cost surface built from the layers
  above, in the shares the planner sets.
- **Heat** comes from a gradient-boosted model trained on 300,000 cells of
  Srinagar district to predict surface temperature from vegetation, canopy,
  roofs, land cover, water, terrain and the surroundings. Tested on whole
  3 km blocks it never saw, its typical error is 2.33 °C (root mean square)
  and it explains 88% of the variation. A change of surface is simulated by
  changing a cell's inputs and predicting again.
- **Flood** is a screening index from recorded water, low ground, height
  above the nearest water and flatness. It is not a hydraulic model.
- **Stress and greening priority** compare zones inside one district. They
  are not absolute measures.

## What it does not claim

- Surface temperature is not air temperature. It is a mid-morning satellite
  reading of the ground.
- Tree-equivalents turn canopy area into a familiar unit at 25 m² a tree.
  They are not a tree count.
- A mitigation zone is land that looks suitable from the data. Ownership and
  permission are not known.
- Air quality is one modelled value per district. Main roads stand in for
  traffic pollution when zones are ranked.
- News reports are sorted by keywords for now, so some are filed under the
  wrong type. A language model on Amazon Bedrock is wired in to read them
  properly and is switched on by setting a model id.
- Every figure is a screening estimate to guide where to look, and should be
  checked on the ground before it is relied on.

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

## On AWS

One EC2 machine runs the database, API, worker and website with Docker
Compose and serves HTTPS itself. The dataset and each release of the code are
kept in S3, and the machine picks a new release up by itself.
`deploy/README.md` has the steps and `deploy/stack.yaml` creates it in one
command.

## Layout

```
backend/app.py            API
backend/worker.py         runs queued analyses, refreshes Environmental Watch
backend/services/         pipeline, thermal model, layers, watch, climate, stress
backend/scripts/          data building, routing, impact and mitigation
frontend/src/pages/       one file per page
frontend/src/components/  shared parts: navigation, map, panels
deploy/                   containers and the AWS stack
```
