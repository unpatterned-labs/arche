# Docker and deploy

One image with every parser and both models inside it, and nothing fetched at runtime. At the end of this page it is answering on your machine, as a service and as an MCP server, behind a proxy that asks who you are.

```sh
docker run --rm -p 8766:8766 ghcr.io/unpatterned-labs/arche-core
```

```sh
curl http://localhost:8766/livez
```

```json
{"ok": true, "version": "0.9.0", "warm": true}
```

`warm: true` means GLiNER 2, GLiNER2-PII and docling's converter loaded at startup, so the first document does not pay for them. `/capabilities` lists the parsers and endpoints this build has. The image runs as a non-root user, on CPU, with `HF_HUB_OFFLINE=1`: it cannot download a model even if asked, because the build already failed if one did not load.

`:latest` is the last release, `:0.9.0` pins one, `:edge` is the tip of `main`.

## The same image, any command

`arche` is the entrypoint, so every subcommand works as an argument. The default is `serve`.

```sh
docker run --rm -i ghcr.io/unpatterned-labs/arche-core mcp                     # the MCP server on stdio
docker run --rm ghcr.io/unpatterned-labs/arche-core redact --text "..." --jurisdiction NG
docker run --rm -v arche-data:/data ghcr.io/unpatterned-labs/arche-core attest keygen /data/signing.pem
```

The MCP line is what an agent config points at (`-i` keeps stdin open; the config is on [Let an agent call arche](../guides/mcp-server.md)). Mount `/data` to keep the ledger and the signing key between runs:

```sh
docker run --rm -p 8766:8766 -v arche-data:/data \
    -e ARCHE_SIGNING_KEY=/data/signing.pem \
    ghcr.io/unpatterned-labs/arche-core
```

With the key set, every answer carries a signed attestation an auditor can verify with `arche attest verify`.

## With an auth proxy: `deploy/`

The service and the MCP server have no authentication of their own, on purpose: who may reach them is the deployment's decision, made once, in front of them. The repository's [`deploy/`](https://github.com/unpatterned-labs/arche/tree/main/deploy) directory is the smallest arrangement that is honest about that.

```sh
git clone https://github.com/unpatterned-labs/arche && cd arche
export ARCHE_HASH_KEY="$(openssl rand -hex 32)"      # keep it; tokens depend on it
docker compose -f deploy/compose.yaml up
```

Three containers: `arche` (the HTTP service), `mcp` (the same tools over streamable HTTP) and `proxy` (Caddy, the only published port). The proxy authenticates, forwards `/mcp` to the MCP server and everything else to the service, and sets `X-Arche-Caller`, which the service records as the caller on every attested answer. So the receipt names a person, not a container.

```sh
curl -u arche:change-me http://localhost:8080/livez
curl -u arche:change-me -F files=@invoice.pdf -F entity=organisation -F jurisdiction=NG \
     http://localhost:8080/documents
```

The password is `change-me` until you change it; the Caddyfile says how, and how to replace basic auth with your identity provider when there is a second person. `ARCHE_VERSION=0.9.0` pins the image; `--build` builds it from the checkout instead.

## Air-gapped

The image needs no network to run. To move it into a network with no egress at all:

```sh
docker save ghcr.io/unpatterned-labs/arche-core:0.9.0 | gzip > arche.tar.gz
# carry it across
docker load < arche.tar.gz
```

Both models, the parsers, OCR, Splink and the ledger work without a connection.

## What the compose file is not

One ledger per process, one key, one set of users; a twenty-page scan holds its request open while it parses (the proxy allows ten minutes). Helm charts, autoscaling and multi-tenant workspaces are somebody's product, not this repository's.
