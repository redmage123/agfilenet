# AG FileNet migration workbench

A local web application for the FileNet/DataCap → CAJS migration files in `data/`.
It reads every PDF and scanned image, builds the metadata the files are missing,
points out problems that need a person's decision before migration, and lets you
search the collection by keyword, by meaning, or with an Interactive Activation
and Competition (IAC) network. Every search result carries a match probability.

**Nothing leaves this machine.** OCR and text embeddings use open-source models
that run locally; the documents contain passports, National Insurance numbers
and medical details.

## Running it

```sh
# once
python3 -m venv .venv
.venv/bin/pip install -e src/backend
(cd src/frontend && npm install && npm run build)

# ingest (OCR takes roughly 10–15 s per scanned page on 4 CPU cores)
.venv/bin/python -m agfilenet ingest

# serve the app at http://127.0.0.1:8000
.venv/bin/python -m agfilenet serve
```

The first ingest downloads the OCR and embedding models (about 100 MB) into the
local model caches; after that no network is needed. Ingest can also be started
from the Overview page. Re-running it only reads new or changed files.
`python -m agfilenet analyse` re-derives metadata from the stored page text
without repeating OCR (use it after changing the rules in `metadata.py`).

The database is a single-process file: stop the server before running `ingest`
or `analyse` from the command line.

For front-end development run `npm run dev` in `src/frontend` (Vite proxies
`/api` to port 8000). Tests: `cd src/backend && ../../.venv/bin/python -m pytest`.

Settings (environment variables): `AGFILENET_DATA` (source folder, default
`data/`), `AGFILENET_VAR` (database and page-image cache, default `var/`).

## Running it in Docker

```
docker compose up -d --build        # then open http://127.0.0.1:8000
docker compose logs -f              # watch it
docker compose down                 # stop it
```

`./data` is mounted read-only and `./var` holds the object database, so the
container uses the same files as a local run. Start the first ingest from the
Overview page, or with `docker compose run --rm app ingest` while the server
is stopped. Do not run the container and a local server against the same `var`
at once: the database is opened by one process at a time.

The embedding and OCR models are inside the image, and the container is told
not to contact the model hub, so documents are processed without any network
access (an ingest under `--network none` works). The port is published on
127.0.0.1 only because the app has no login; change the `ports` line in
`docker-compose.yml` only behind something that adds one. Set `AGFILENET_PORT`
to use a different port.

## What it does

**Ingest** (`ingest.py`, `extract.py`, `ocr.py`) — walks the source folder; uses the
PDF text layer where there is one, otherwise OCR (RapidOCR). Pages that read
badly are retried at 90/180/270° and the rotation is recorded. Declared metadata
is imported from the migration workbooks (`workbook.py`).

**Metadata** (`metadata.py`) — rule-based, so every value can be traced to the text:

- document type per page from heading phrases, and the type of the file overall
- *segments*: where one file holds several documents (bundles)
- date, subject, parties (from court headings), a generated title
- people, organisations, court/case numbers, file references, registry volumes
- duplicate pages (near-identical text, within and across files) and identical files
- checks: bundle, duplicates, rotated pages, low OCR confidence, type differs from
  the workbook, no type in the workbook, passport / National Insurance / date of
  birth / medical content

Derived values can be corrected on the document page; corrections are kept when
the metadata is re-derived. `Download metadata (CSV)` exports everything next to
the workbook's declared values.

**Storage** (`store.py`) — an object database (ZODB). A `Library` root object owns
`Document` objects; each document owns its `Page`, `Segment` and `Chunk` objects and
references `Entity` objects through `Mention`s, and entities reference their
documents back. BTrees on the library give lookup by id, path and entity; a
persistent `TextIndex` (inverted index, BM25) serves keyword retrieval.

**Search** (`search.py`, `iac.py`)

| Mode | How it scores | Probability shown |
|---|---|---|
| Keyword | BM25 over ~160-word passages; `"quoted phrases"` must appear | saturating share of the best possible score (rule of thumb) |
| Semantic | cosine similarity of the query and passage embeddings (bge-small) | similarity rescaled to 0–1 (rule of thumb) |
| Hybrid | either kind of evidence counts | noisy-OR of the two |
| IAC | the network below | calibrated curve over settled activation |

### The IAC network

After McClelland & Rumelhart's `iac` model (*Explorations in Parallel Distributed
Processing*). Units sit in pools: **documents**, **query terms**, **entities**,
**matters** and **document types**. A document is linked by symmetric excitatory
weights to its terms (BM25-style weight), its entities, its matter and its type;
rarer properties get stronger links. The query supplies external input to its
term units, to any entity/matter/type it names, and to each document unit in
proportion to semantic similarity. The network is then cycled to equilibrium
with the standard update rule (max 1, min −0.2, rest −0.1, decay 0.1, estr 0.4,
alpha 0.1, gamma 0.1).

Because activation flows document → property → document, a file that does not
contain the query words can still be retrieved through a shared person,
reference or matter; the result list says when that happened and which units
supplied the input.

Deviations from the textbook model, chosen deliberately: only the document,
matter and type pools are competitive (a document can mention many people and
terms at once); inhibition between documents is halved so that several
documents can be right together; and the query's words share a fixed budget of
influence, so a file matching two words of a two-word query outranks one
matching two of five. A case number, file reference or matter number quoted in
the query is treated as the strongest evidence there is: its link is doubled and
that part of the query contributes nothing to the semantic input, because a
reference number has no meaning for an embedding model to match. The link strengths at the top of `search.py` were set by
hand against a handful of queries on these 48 files — they are a starting
point, not a fitted model.

**Probabilities.** *Match* is a logistic function of a document's settled
activation. Until there are relevance judgements it uses a default curve and is
**not calibrated** — treat it as a ranking aid. The “Is this a match? Yes / No”
links on each result store judgements; once there are 20 (at least 5 of each)
the curve is fitted to them. *Best* is the Luce choice rule over the returned
documents plus a “none of these” alternative, so those sum to 100%.

## Limits

- OCR is good on typed text and poor on handwriting, stamps and faint faxes;
  low-confidence files are flagged rather than trusted.
- Metadata rules were written for the document kinds seen in the two
  demonstrator packages. New kinds will show as “not identified” until a rule
  is added to `TYPE_RULES`.
- Bundle splitting and party extraction are heuristics; check flagged files.
- The index is rebuilt in memory when content changes; that suits thousands of
  documents, not millions.
