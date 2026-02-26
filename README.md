# pykoclaw-matrix

[![Built with Claude Code](https://img.shields.io/badge/Built_with-Claude_Code-6f42c1?logo=anthropic&logoColor=white)](https://claude.ai/code)

> This project is developed by an AI coding agent ([Claude Code](https://claude.ai/code)), with human oversight and direction.

Matrix/Element channel plugin for [pykoclaw][pykoclaw]. Connects pykoclaw's AI
agent to Matrix rooms via the [matrix-nio][nio] library.

## Features

- **End-to-end encryption** — full E2EE support for encrypted rooms via
  libolm/matrix-nio.
- **Ambient listening** — the agent monitors Matrix rooms and only replies when
  directly mentioned or in DMs.
- **Rich formatting** — agent Markdown is converted to Matrix HTML
  (`org.matrix.custom.html`) for bold, italic, code blocks, tables,
  strikethrough, blockquotes, lists, and auto-linked URLs.
- **Mermaid diagrams** — `` ```mermaid `` `` code blocks are rendered to hi-res
  PNG images (2× device scale) and sent as `m.image` events inline.
- **Image file uploads** — absolute paths to image files (PNG, JPEG, GIF, WebP,
  etc.) in agent responses are automatically read from disk and sent as
  `m.image` events at the correct position in the conversation.
- **Task list rendering** — `- [x]` / `- [ ]` task lists render as ✅ / ⬛
  emoji checkboxes on `<br>`-separated lines (Element strips `<input>`
  elements). Nested task lists are indented with Braille blanks.
- **Typing indicator** — shows "user is typing…" in Element while the agent
  processes a message.
- **Batch accumulation** — groups rapid messages into a single agent prompt
  (configurable window). DMs and direct mentions flush immediately.
- **Cross-signing** — built-in `verify` command bootstraps cross-signing so
  the bot's messages don't show red "unverified" warnings in Element.
- **Auto-join** — automatically joins rooms when invited (configurable).
- **Delivery queue** — scheduled task results are delivered via the standard
  pykoclaw delivery queue.
- **MCP tools** — exposes `send_matrix_message` and `get_matrix_history` to the
  agent.

## Quick start

### 1. Create a Matrix account for the bot

Create a dedicated Matrix account on your homeserver (e.g. via Element).

### 2. Get an access token

```bash
pykoclaw matrix login
```

Follow the prompts. The command prints the access token and device ID.

### 3. Configure

Add to your `.env` file (or set environment variables):

```env
PYKOCLAW_MATRIX_HOMESERVER=https://matrix.example.com
PYKOCLAW_MATRIX_USER_ID=@bot:matrix.example.com
PYKOCLAW_MATRIX_ACCESS_TOKEN=syt_...
PYKOCLAW_MATRIX_DEVICE_ID=ABCDEFGHIJ
PYKOCLAW_MATRIX_TRIGGER_NAME=Andy
```

### 4. Cross-sign the device (recommended)

```bash
pykoclaw matrix verify
```

This bootstraps cross-signing keys so the bot's messages don't show red
"unverified device" warnings in Element. On matrix.org, you'll be prompted
to approve the reset via a browser URL.

### 5. Run

```bash
pykoclaw matrix run
```

## Configuration

All settings use the `PYKOCLAW_MATRIX_` env prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOMESERVER` | `https://matrix.org` | Matrix homeserver URL |
| `USER_ID` | — | Bot's Matrix user ID (`@user:server`) |
| `ACCESS_TOKEN` | — | Access token (preferred over password) |
| `PASSWORD` | — | Account password (used if no access token) |
| `DEVICE_NAME` | `pykoclaw` | Device name shown in sessions |
| `DEVICE_ID` | — | Device ID for session persistence |
| `STORE_PATH` | `~/.local/share/pykoclaw/matrix/store` | nio crypto/state store |
| `TRIGGER_NAME` | `Andy` | Name the agent responds to |
| `BATCH_WINDOW_SECONDS` | `90` | Batch accumulation window |
| `AUTO_JOIN` | `true` | Auto-join rooms when invited |

## Prerequisites

Mermaid diagram rendering requires [Playwright][playwright] with Chromium. On
NixOS / the production service this is handled via `nix-shell -p chromium`;
elsewhere, ensure Chromium is available on `$PATH` or set
`$PLAYWRIGHT_BROWSERS_PATH`.

## Architecture

The plugin follows the same patterns as [pykoclaw-whatsapp][wa]:

- **`MatrixPlugin`** — entry point registered via `pykoclaw.plugins`. Registers
  CLI commands, DB migrations, config class, and MCP tools.
- **`MatrixConnection`** — manages the matrix-nio `AsyncClient` lifecycle,
  event callbacks, sync loop, and delivery polling. Outgoing messages are split
  into interleaved text and image segments so that images appear inline.
- **`BatchAccumulator`** — per-room timer-based batch accumulation with
  immediate flush on hard mentions / DMs.
- **`handler`** module — message storage, XML formatting, mention detection,
  cursor tracking.
- **`formatting`** module — Markdown → Matrix HTML conversion via
  [markdown-it-py][mipy] with GFM table, strikethrough, linkify, and task list
  support.
- **`mermaid`** module — extracts `` ```mermaid `` `` code blocks and renders
  them to PNG via [mermaid-cli][mcli] (Playwright + Chromium).
- **`images`** module — detects absolute image file paths in agent text,
  verifies they exist on disk, and provides MIME type helpers.
- **`segments`** module — splits agent text into ordered `TextSegment` /
  `ImageSegment` entries so the caller can send them as separate Matrix
  messages in document order.

All agent dispatch goes through `pykoclaw-messaging`'s `dispatch_to_agent()`.
Conversations are named `matrix-{room_id}`.

## Database tables

- **`matrix_messages`** — stores all incoming/outgoing messages per room.
- **`matrix_rooms`** — tracks per-room timestamps and agent cursors.

[pykoclaw]: ../pykoclaw/
[nio]: https://github.com/poljar/matrix-nio
[wa]: ../pykoclaw-whatsapp/
[playwright]: https://playwright.dev/python/
[mipy]: https://github.com/executablebooks/markdown-it-py
[mcli]: https://pypi.org/project/mermaid-cli/
