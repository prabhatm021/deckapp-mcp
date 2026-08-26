# deckapp-mcp

MCP support for [DeckApp](https://github.com/prabhatm021/deckapp), so tools like
Claude can build and run your decks. It works on the same deck files as the app,
whether or not DeckApp is open.

## Requirements

DeckApp 3.0 or newer, installed so that `import deckapp` works. The .deb puts it
in `/usr/lib/python3/dist-packages`, which a virtualenv can see if you create it
with `--system-site-packages`.

## Install

```bash
git clone https://github.com/prabhatm021/deckapp-mcp.git
cd deckapp-mcp
python3 -m venv --system-site-packages .venv
.venv/bin/pip install .
```

Check it found DeckApp:

```bash
.venv/bin/python -c "import deckapp; print(deckapp.__version__)"
```

## Connect it

Claude Code:

```bash
claude mcp add deckapp -- /path/to/deckapp-mcp/.venv/bin/deckapp-mcp
```

Claude Desktop, or any client with a JSON config:

```json
{
  "mcpServers": {
    "deckapp": {
      "command": "/path/to/deckapp-mcp/.venv/bin/deckapp-mcp"
    }
  }
}
```

Use the full path. The venv's `deckapp-mcp` is the one that knows where DeckApp
lives.

## Tools

26 of them, covering the same ground as the app: create, rename, resize,
duplicate, reorder and delete decks; add, edit, move and remove buttons; import
icons; read and set toggle states; export and import a deck as JSON; open a deck
window. Run `list_decks` first to see what ids you have.

There is also `press_button`, which runs a button's command and hands back the
exit code and output. That makes it easy to check a deck works, and it means
anything connected to this server can run whatever your decks run. It is shell
access, so treat it that way.

Positions are zero indexed, row 0 column 0 being the top left key.

## License

[MIT](LICENSE)
