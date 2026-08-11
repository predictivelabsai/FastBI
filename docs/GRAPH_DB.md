# FastBI graph database

Implemented 11 August 2026.

FastBI keeps SQLite as its primary analytical and application database. Neo4j
is an optional secondary store for ontologies and relationship questions. It is
disabled cleanly when `FASTBI_GRAPH_ENABLED=0`.

## Delivered sequence

1. A self-hosted Neo4j 5.26 Community container with persistent `/data` storage.
2. A bounded JSON/YAML ontology contract with preview, canonical hashing, and
   atomic idempotent imports.
3. Admin-only import, version history, activation, and rollback controls.
4. A Vis Network graph explorer with ontology filters and property inspection.
5. A read-only Cypher Lab and schema-grounded text-to-Cypher, parallel to the
   existing SQL Lab and text-to-SQL path.
6. Automatic conversational routing with explicit Auto, SQL, and Graph modes.
7. Token-gated graph schema and query API endpoints.

## Ontology contract

Use UTF-8 `.json`, `.yaml`, or `.yml`. Import limits default to 2 MB, 5,000
nodes, and 10,000 relationships. Node labels, relationship types, and property
keys use safe identifiers; properties can contain scalars or scalar lists.

```yaml
ontology:
  id: retail-bi
  name: Retail BI ontology
  version: "1.0"
nodes:
  - id: order
    type: Entity
    label: Order
    properties:
      source_table: wh_orders
  - id: revenue
    type: Metric
    label: Revenue
edges:
  - from: revenue
    to: order
    type: MEASURES
```

The complete starter ontology is in
[`examples/retail-ontology.yaml`](../examples/retail-ontology.yaml).

## Local run

```bash
cp .env.sample .env
# Set FASTBI_ADMIN_PASSWORD and a strong NEO4J_PASSWORD in .env.
docker compose up --build
```

- FastBI: `http://127.0.0.1:5008`
- Neo4j Browser: `http://127.0.0.1:7474`
- Bolt: `bolt://127.0.0.1:7687`

Compose enables the graph engine and automatically imports the bundled retail
ontology on an empty graph. Native runs remain graph-disabled unless the graph
environment variables are explicitly enabled.

## Production configuration

Run Neo4j as a private Coolify application on the shared internal Docker
network. Do not publish the Browser or Bolt ports. Persist `/data`, then set the
following on FastBI:

```ini
FASTBI_GRAPH_ENABLED=1
FASTBI_GRAPH_AUTOSEED=1
FASTBI_GRAPH_ADMIN_EMAILS=admin@example.com
NEO4J_URI=bolt://<coolify-internal-host>:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<secret>
NEO4J_DATABASE=neo4j
```

Operational checks:

```bash
curl -fsS https://fastbi.org/healthz
curl -fsS https://fastbi.org/api/v1/graph/health
```

`/healthz` reports SQLite and graph state. Graph schema/query endpoints remain
bearer-token protected, while `/api/v1/graph/health` exposes only safe status
and counts.

## Safety model

- Imports are restricted to configured graph administrators and are applied in
  one managed Neo4j write transaction.
- Cypher must start with `MATCH` or `OPTIONAL MATCH`, return a bounded result,
  and cannot invoke writes, procedures, administration, comments, or multiple
  statements.
- Queries are validated, explained, timed out, and capped before results are
  rendered.
- The LLM never receives database credentials and cannot execute queries
  directly; generated Cypher passes through the same guard as manually entered
  Cypher.
