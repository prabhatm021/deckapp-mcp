# deckapp-mcp

An MCP server for [DeckApp](https://github.com/prabhatm021/deckapp), the Linux
macro pad. It lets an assistant build decks, wire buttons to shell commands,
press them and report what came back.

It reads and writes the same deck files as the app, so it works whether or not
DeckApp is open.

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

## Point a client at it

Claude Code:

```bash
claude mcp add deckapp -- /path/to/deckapp-mcp/.venv/bin/deckapp-mcp
```

Any client that takes a JSON config:

```json
{
  "mcpServers": {
    "deckapp": {
      "command": "/path/to/deckapp-mcp/.venv/bin/deckapp-mcp"
    }
  }
}
```

Use the full path. The venv's `deckapp-mcp` is what knows where DeckApp lives.

## What it can do

Decks: `list_decks`, `get_deck`, `new_deck`, `rename_deck`, `resize_deck`,
`remove_deck`, `duplicate_deck`, `set_deck_order`, `export_deck`, `import_deck`

Buttons: `set_button`, `get_button`, `move_button`, `remove_button`,
`clear_deck`, `find_buttons`, `press_button`

Toggles: `get_toggle_states`, `set_toggle_state`

Icons: `add_icon`, `set_button_icon`, `list_icons`, `remove_unused_icons`

The app: `open_deck_window`, `app_status`, `app_version`

There are also two resources, `deckapp://decks` and `deckapp://deck/{id}`, which
return the same data as JSON.

Positions are zero indexed, so row 0 column 0 is the top left key.

## A note on press_button

`press_button` runs that button's command in a shell and hands back the exit
code, stdout and stderr. That makes it easy to check a deck actually works, and
it also means an assistant with access to this server can run anything your
decks can run. Treat it the way you would treat giving something shell access,
because that is what it is.

## Example

Asking an assistant for "a deck for my morning routine" gets you something like:

```
new_deck(name="Morning", rows=2, cols=3)
set_button(deck_id="morning", row=0, col=0, label="Standup",
           behavior="single", command="firefox https://meet.example.com/standup")
set_button(deck_id="morning", row=0, col=1, label="Focus", behavior="toggle",
           on_command="gsettings set org.gnome.desktop.notifications show-banners false",
           off_command="gsettings set org.gnome.desktop.notifications show-banners true")
press_button(deck_id="morning", row=0, col=0)
```

## License

[MIT](LICENSE)
