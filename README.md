# NYC Transit Resilience Engine

A data engineering and transportation-network analysis project built around the NYC subway system.

The goal is to model the NYC subway as a transportation network and investigate how the system behaves under disruptions such as station closures, line shutdowns, and capacity reductions.

This project is being developed incrementally, starting with the MTA's GTFS static data and eventually expanding into historical transit analysis, graph theory, geospatial analysis, and large-scale simulation.

## Project Goals

The eventual system will be able to investigate questions such as:

- Which subway stations are most critical to network connectivity?
- What happens when a station or track segment becomes unavailable?
- How much additional travel time does a disruption create?
- Which areas of NYC are most affected by transit failures?
- How do historical disruptions propagate through the network?
- Which alternative routes and stations absorb displaced passengers?
- How resilient is the NYC subway network under different failure scenarios?

The project is primarily an **analytical and simulation system**, rather than a navigation application like Citymapper or Apple Maps.

---

## Planned Architecture

```text
MTA GTFS
    │
    ├── Routes
    ├── Trips
    ├── Stops
    ├── Stop Times
    └── Shapes
          │
          ▼
    Data Ingestion
          │
          ▼
    Parquet Data Lake
          │
          ▼
    Data Processing
          │
          ▼
    Transit Network
          │
          ▼
    Graph Analysis
          │
          ▼
    Failure Simulation
          │
          ▼
    Resilience Analysis
          │
          ▼
    Visualization / Web Application
```

Future versions may incorporate additional datasets such as:

- MTA GTFS-Realtime
- MTA ridership data
- NYC Open Data
- NYC GIS datasets
- U.S. Census data
- Weather data

---

## Current Status

### Milestone 1 — GTFS ingestion and network foundation

**In progress**

Current work includes:

- [x] Obtain NYC MTA subway GTFS data
- [x] Establish project structure
- [x] Load GTFS datasets
- [x] Convert raw GTFS data to Parquet
- [x] Identify the relationship between stations and platform-level stops
- [x] Normalize stations and platforms
- [ ] Construct transit edges from ordered `stop_times`
- [ ] Build the initial subway graph
- [ ] Geographically visualize the network

### Planned milestones

#### Milestone 2 — Transit Network Graph

- Construct the NYC subway graph
- Represent stations and platform-level stops
- Associate routes with network edges
- Preserve direction and stop sequence
- Calculate travel times

#### Milestone 3 — Graph Analysis

Investigate:

- Degree centrality
- Betweenness centrality
- Closeness centrality
- Connected components
- Articulation points
- Shortest paths
- Network bottlenecks

#### Milestone 4 — Failure Simulation

Simulate:

- Station closures
- Track/edge failures
- Line shutdowns
- Service reductions

Measure:

- Network fragmentation
- Additional travel time
- Unreachable stations
- Affected portions of the network
- Alternative routing

#### Milestone 5 — Ridership and Accessibility

Integrate ridership and geographic data to estimate:

- Passengers affected by disruptions
- Accessibility loss
- Neighborhood-level impacts
- Passenger redistribution

#### Milestone 6 — Historical Transit Analysis

Integrate historical MTA service and disruption data to investigate:

- Delay patterns
- Recurring disruptions
- Line reliability
- Failure propagation
- Recovery times

#### Milestone 7 — Big Data Processing

Introduce distributed processing where appropriate.

Potential technologies:

- Apache Spark / PySpark
- Parquet
- DuckDB
- Partitioned datasets

Processing performance will be compared against local approaches where useful.

#### Milestone 8 — Transit Resilience Engine

Build a scenario engine capable of answering questions such as:

> What happens if this station closes during rush hour?

> What happens if an entire subway line loses 30% of its capacity?

> Which stations are most critical to overall network resilience?

#### Milestone 9 — Visualization

Build an interactive interface for exploring:

- Network structure
- Station criticality
- Historical disruptions
- Failure scenarios
- Accessibility changes
- Network resilience

---

## Technology

### Current

- Python
- Pandas
- PyArrow
- Parquet
- NetworkX
- Matplotlib

### Planned

- GeoPandas
- Shapely
- DuckDB
- PySpark
- FastAPI
- PostgreSQL / PostGIS
- MapLibre GL JS

Technologies will be introduced as the project's data and computational requirements justify them rather than being added solely for the sake of the technology stack.

---

## Data

The initial dataset is the **NYC MTA Subway GTFS static feed**.

GTFS provides standardized public transportation information including:

- Agencies
- Routes
- Trips
- Stops
- Stop times
- Service calendars
- Transfers
- Geographic shapes

The raw GTFS files are not committed to this repository.

See the MTA's official developer/transit data resources for the current dataset.

### Data handling

Raw data is stored locally under:

```text
data/raw/
```

Processed datasets are generated under:

```text
data/processed/
```

The repository intentionally excludes generated and downloaded data files. This keeps the Git repository lightweight and makes the data pipeline reproducible.

---

## Project Structure

```text
nyc-transit-resilience/
│
├── data/
│   ├── raw/
│   │   └── MTA GTFS files
│   │
│   └── processed/
│       └── generated Parquet datasets
│
├── src/
│   ├── ingestion/
│   │   └── GTFS ingestion
│   │
│   ├── processing/
│   │   └── data cleaning and normalization
│   │
│   ├── graph/
│   │   └── transit network construction and analysis
│   │
│   └── visualization/
│       └── network visualization
│
├── notebooks/
│   └── exploratory analysis
│
├── tests/
│   └── automated tests
│
├── requirements.txt
├── README.md
└── .gitignore
```

---

## Why This Project?

Transportation systems are naturally represented as networks.

A subway station can be modeled as a node, while connections between stations can be modeled as edges. Once represented this way, graph theory can be used to study the structure and resilience of the system.

The project goes beyond simply finding the fastest route between two stations.

The central question is:

> **How does NYC's transportation network behave when part of the system changes or fails?**

This creates an opportunity to combine:

**Data Engineering + Graph Theory + GIS + Statistics + Simulation + Big Data**

using a real-world infrastructure system.

---

## Long-Term Vision

The final system should function as a small-scale transportation systems laboratory.

A user could select a station, line, or network segment and run a hypothetical disruption:

```text
Station:
[ Times Sq–42 St ]

Scenario:
[ Station Closure ]

Duration:
[ 6 hours ]

Passenger Impact:
[ Enabled ]

        ↓

    RUN SIMULATION
```

The system could then estimate the resulting network-wide effects and visualize them geographically.

---

## Disclaimer

This is an educational and research project.

Results produced by the simulation should not be interpreted as official MTA transportation planning recommendations. Real transportation systems involve operational, safety, capacity, scheduling, and passenger-behavior considerations that may not be represented by the model.
