# SpiceMCP

MCP server for SPICE circuit simulations. Lets LLMs write and simulate SPICE netlists, read structured results, and iterate on designs — without touching raw output files.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Docker (for the default simulator backends)

## Install

```bash
git clone https://github.com/aanas-sayed/spicemcp
cd spicemcp
uv sync
```

## Pull simulator images

```bash
# Linux / Windows / macOS (Intel)
docker compose -f docker/docker-compose.yml pull --profile simulators

# macOS on Apple Silicon (Docker Desktop or Colima)
docker compose -f docker/docker-compose.yml pull --profile macos
```

> **Apple Silicon:** The `macos-latest` tag is pinned to Wine 9.0. Wine 10+ crashes under QEMU user-mode emulation on 16 KB page-size hosts. Do not use `--platform linux/amd64` with the `latest` tag on Apple Silicon.

## Run

```bash
uv run spicemcp
```

Or add to your Claude Code / Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "spicemcp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/spicemcp", "spicemcp"]
    }
  }
}
```

## Configuration

SpiceMCP looks for `~/.config/spicemcp/config.json` (or set `SPICEMCP_CONFIG`):

```json
{
  "simulators": {
    "ltspice": { "backend": "docker", "image": "aanas-sayed/docker-ltspice:latest", "timeout_s": 300 },
    "ngspice":  { "backend": "docker", "image": "aanas-sayed/docker-ngspice:latest", "timeout_s": 300 }
  },
  "model_dirs": ["/path/to/your/models"],
  "session_ttl_minutes": 10,
  "max_raw_size_mb": 200
}
```

### Local simulator override

```json
{
  "simulators": {
    "ltspice": { "backend": "local", "executable": "/usr/local/bin/ltspice" }
  }
}
```

### Docker-in-Docker (dev containers, CI)

If SpiceMCP itself runs inside a container, mount the Docker socket:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock ...
```

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src/
```

## License

MIT
