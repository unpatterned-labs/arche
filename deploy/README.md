# Deploying arche

One image, ready to receive documents and tool calls. Every parser and model is inside it; nothing is fetched at runtime. The same image runs on a laptop, on a server in your own building, or on a cloud VM -- that is the point, and it is what the data-sovereignty rule requires.

This directory is the smallest arrangement that is honest about auth: the service, the MCP server, and a proxy that asks who you are. It is not a platform. Helm charts, autoscaling and multi-tenant workspaces are somebody's product, not this repository's.

## Run it

```sh
export ARCHE_HASH_KEY="$(openssl rand -hex 32)"      # keep it; tokens depend on it
docker compose -f deploy/compose.yaml up
```

That pulls `ghcr.io/unpatterned-labs/arche-core` (`ARCHE_VERSION=0.9.0` pins one; `--build` builds it from this checkout instead, a few GB of models once). Then:

```sh
curl -u arche:change-me http://localhost:8080/livez
# {"ok": true, "version": "0.9.0", "warm": true}

curl -u arche:change-me -F files=@invoice.pdf -F files=@po.pdf \
     -F entity=organisation -F jurisdiction=NG \
     http://localhost:8080/documents
```

`warm: true` means the models loaded at startup and the first document does not pay for them. `/capabilities` lists the parsers and endpoints this build has.

The password is `change-me` until you change it; the Caddyfile says how.

## What is running

| container | what | where |
|---|---|---|
| `arche` | `arche serve`: the verbs over HTTP | `http://localhost:8080/` through the proxy |
| `mcp` | `arche mcp --transport streamable-http`: the same verbs as MCP tools | `http://localhost:8080/mcp` through the proxy |
| `proxy` | Caddy: authenticates, sets `X-Arche-Caller`, streams MCP answers | the only published port, `8080` |

Point an MCP client at `http://localhost:8080/mcp` with the basic-auth header. For a client on the same machine that speaks stdio, skip the proxy: `docker run -i --rm -e ARCHE_HASH_KEY ghcr.io/unpatterned-labs/arche-core mcp`.

## What is in the image

| | |
|---|---|
| **parsers** | plain text; PDF (`pypdf`); DOCX; docling for layout-aware parsing of everything else; RapidOCR for scanned pages -- pure ONNX, no torch, no tesseract |
| **models** | GLiNER 2 (general extraction) and GLiNER2-PII (personal data), Apache-2.0, loaded on-device -- the `[local]` stack, never the API client |
| **matching** | arche's engine, plus Splink and DuckDB for `backend="auto"` above the size floor |
| **ledger** | `/data/ledger.duckdb` (service) and `/data/mcp-ledger.duckdb` (MCP) on one named volume; every decision, replayable. Two files because DuckDB allows one writing process per database |
| **attestation** | off until `ARCHE_SIGNING_KEY` names a key made by `arche attest keygen` |

The build fails if any model does not load. That is deliberate: a container that starts and then downloads on the first request has not been deployed, it has been postponed.

## The verbs

| | |
|---|---|
| `POST /documents` | files in, one resolved record per document out, masked unless `reveal=true` |
| `POST /detect`, `POST /deidentify` | the personal data with the statute section, and the copy the statute permits |
| `POST /compare` | two records or two texts, one verdict with evidence |
| `POST /places` | place mentions with their spatial role |
| `POST /extract` | proposed entities of the types you name |
| `GET /decision/{id}`, `/explain/{id}`, `/replay/{id}` | the ledger, by id |
| `/mcp` | the ten MCP tools, eighteen with a ledger -- see [Let an agent call arche](https://arche.unpatterned.org/guides/mcp-server/) |

## Auth, and who the caller is

Neither the service nor the MCP server authenticates. Inside the compose network they bind every interface; only the proxy is published. The proxy authenticates and sets `X-Arche-Caller`, which both the HTTP service and the MCP server over streamable HTTP record as the caller on every attested answer, so the receipt names a person rather than a container. Over stdio there is no caller to name and the field stays null.

The shipped Caddyfile uses a single basic-auth user. Replace it with `forward_auth` to your identity provider when there is a second person; nothing in the service changes.

## Signing answers

```sh
docker compose -f deploy/compose.yaml run --rm arche attest keygen /data/signing.pem
```

prints the `did:key` to publish. Uncomment `ARCHE_SIGNING_KEY` in `compose.yaml`, restart, and every answer carries a JWS an auditor can verify with `arche attest verify`.

## On-premise, air-gapped

The image runs without network access to fetch models (`HF_HUB_OFFLINE=1`). To move it into a network with no egress at all: `docker save ghcr.io/unpatterned-labs/arche-core:0.9.0 | gzip > arche.tar.gz`, carry it across, `docker load`. Everything in the table above works without a connection.

## What this is not, yet

- **One workspace.** One ledger per process, one key, one set of users. A header-to-ledger map is the next thing, and it is not here.
- **Synchronous.** A twenty-page scan holds the request open while it parses. The proxy allows ten minutes. Batches that need a job id are after that.
- **A caller on MCP answers.** See above.
