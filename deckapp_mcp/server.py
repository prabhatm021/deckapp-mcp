"""An MCP server for DeckApp.

Gives an assistant full control of decks, buttons, icons and the running app:

    deckapp-mcp

Everything here works on the deck files directly, so it functions whether or
not the GUI is running. The few tools that talk to a running instance say so in
their docstrings.

Requires DeckApp 3.0 or newer to be importable. Installing the .deb puts it in
/usr/lib/python3/dist-packages, which a virtualenv created with
--system-site-packages can see.
"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from deckapp.core import icons as icon_store
from deckapp.core import prefs              
from deckapp.core.deck_store import (DeckError, create_deck,
                                     delete_deck, list_deck_paths, load_deck,
                                     load_all_decks, save_deck, slugify,
                                     validate_name)
from deckapp.core.models import (Button, MAX_GRID, MIN_GRID,
                                 SINGLE, TOGGLE)
from deckapp.core.paths import get_decks_dir, get_icons_dir
from deckapp.core.state_manager import StateManager 

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover - a clear message beats a traceback
    raise SystemExit("fastmcp is missing. Install it with: pip install fastmcp")

mcp = FastMCP(
    name="DeckApp",
    instructions=(
        "Control DeckApp, a virtual macro pad for Linux. Decks are grids of "
        "buttons that run shell commands. Positions are zero-indexed "
        "(row 0, col 0 is the top-left key). Use list_decks first to learn "
        "the deck ids in play."
    ),
)

Row = Annotated[int, "Zero-indexed row, 0 is the top"]
Col = Annotated[int, "Zero-indexed column, 0 is the left"]


# ── Helpers ──

def _find_deck(deck_id: str):
    """Resolve a deck by id, file name or display name."""
    decks, _errors = load_all_decks()
    wanted = (deck_id or "").strip().lower()
    for deck in decks:
        names = {deck.deck_id.lower(), deck.name.lower()}
        if deck.path:
            names.add(deck.path.stem.lower())
        if wanted in names:
            return deck
    raise ValueError(
        f"No deck matching '{deck_id}'. Known decks: "
        + ", ".join(d.deck_id for d in decks) or "(none)"
    )


def _deck_summary(deck) -> dict:
    return {
        "deck_id": deck.deck_id,
        "name": deck.name,
        "rows": deck.rows,
        "cols": deck.cols,
        "buttons": len(deck.buttons),
        "file": str(deck.path) if deck.path else None,
    }


def _button_summary(button) -> dict:
    data = {
        "row": button.row,
        "col": button.col,
        "label": button.label,
        "behavior": button.behavior,
        "icon": button.icon,
        "configured": button.is_configured(),
    }
    if button.is_toggle:
        data.update(on_command=button.on_command,
                    off_command=button.off_command,
                    state=button.state)
    else:
        data.update(command=button.command)
    return data


def _check_position(deck, row: int, col: int):
    if not (0 <= row < deck.rows and 0 <= col < deck.cols):
        raise ValueError(
            f"Position ({row}, {col}) is outside the {deck.rows} × {deck.cols} "
            f"grid of '{deck.deck_id}'."
        )


def _run_cli(*args) -> str:
    """Talk to a running DeckApp (a single instance forwards the request)."""
    import shutil

    launcher = shutil.which("deckapp")
    command = ([launcher] if launcher
               else [sys.executable, "-m", "deckapp.app"])
    result = subprocess.run(
        [*command, *args], capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()
                           or f"deckapp exited {result.returncode}")
    return (result.stdout or "").strip()


# ── Decks ──

@mcp.tool
def list_decks() -> list[dict]:
    """List every deck, in the order DeckApp shows them."""
    decks, errors = load_all_decks()
    ordered = prefs.apply_deck_order(decks)
    result = [_deck_summary(deck) for deck in ordered]
    if errors:
        result.append({"unreadable_files": errors})
    return result


@mcp.tool
def get_deck(deck_id: str) -> dict:
    """Everything about one deck, including all of its buttons."""
    deck = _find_deck(deck_id)
    summary = _deck_summary(deck)
    summary["button_list"] = [
        _button_summary(button) for _pos, button in sorted(deck.buttons.items())
    ]
    return summary


@mcp.tool
def new_deck(
    name: Annotated[str, "Display name, e.g. 'Media Controls'"],
    rows: Annotated[int, f"{MIN_GRID}-{MAX_GRID}"] = 4,
    cols: Annotated[int, f"{MIN_GRID}-{MAX_GRID}"] = 4,
) -> dict:
    """Create an empty deck."""
    error = validate_name(name)
    if error:
        raise ValueError(error)
    return _deck_summary(create_deck(name, rows, cols))


@mcp.tool
def rename_deck(deck_id: str, new_name: str) -> dict:
    """Change a deck's display name. Its id and file name stay the same, so
    saved toggle states and dock shortcuts keep working."""
    error = validate_name(new_name)
    if error:
        raise ValueError(error)
    deck = _find_deck(deck_id)
    deck.name = new_name.strip()
    save_deck(deck, deck.path)
    return _deck_summary(deck)


@mcp.tool
def resize_deck(deck_id: str, rows: int, cols: int) -> dict:
    """Resize a deck's grid. Buttons outside the new size are removed, and the
    removed ones are reported back."""
    deck = _find_deck(deck_id)
    lost = [_button_summary(b) for b in deck.buttons_lost_by_resize(rows, cols)]
    deck.resize(rows, cols)
    save_deck(deck, deck.path)
    summary = _deck_summary(deck)
    summary["removed_buttons"] = lost
    return summary


@mcp.tool
def remove_deck(deck_id: str) -> dict:
    """Delete a deck file permanently."""
    deck = _find_deck(deck_id)
    delete_deck(deck.path)
    StateManager().forget_deck(deck.deck_id)
    return {"deleted": deck.deck_id, "name": deck.name}


@mcp.tool
def set_deck_order(deck_ids: list[str]) -> list[str]:
    """Set the order decks appear in, top to bottom. Decks left out keep their
    place after the ones listed."""
    keys = [_find_deck(deck_id).path.stem for deck_id in deck_ids]
    prefs.set_deck_order(keys)
    return keys


@mcp.tool
def duplicate_deck(deck_id: str, new_name: str) -> dict:
    """Copy a deck, buttons and all, under a new name."""
    source = _find_deck(deck_id)
    error = validate_name(new_name)
    if error:
        raise ValueError(error)

    copy = create_deck(new_name, source.rows, source.cols)
    for (row, col), button in source.buttons.items():
        copy.place(row, col, Button.from_dict(row, col, button.to_dict()))
    save_deck(copy, copy.path)
    return _deck_summary(copy)


@mcp.tool
def export_deck(deck_id: str) -> str:
    """The deck's file contents as JSON — for backups or sharing."""
    return json.dumps(_find_deck(deck_id).to_dict(), indent=2)


@mcp.tool
def import_deck(
    deck_json: Annotated[str, "A deck file's JSON, as export_deck returns"],
    name: Annotated[Optional[str], "Override the name in the JSON"] = None,
) -> dict:
    """Create a deck from exported JSON."""
    try:
        data = json.loads(deck_json)
    except ValueError as e:
        raise ValueError(f"That is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object describing a deck.")

    wanted = (name or data.get("deck_name") or "Imported deck").strip()
    error = validate_name(wanted)
    if error:
        raise ValueError(error)

    grid = data.get("grid") if isinstance(data.get("grid"), dict) else {}
    deck = create_deck(wanted, grid.get("rows", 4), grid.get("cols", 4))
    for key, button_data in (data.get("buttons") or {}).items():
        try:
            row, col = (int(part) for part in str(key).split(","))
        except (ValueError, TypeError):
            continue
        if 0 <= row < deck.rows and 0 <= col < deck.cols:
            deck.place(row, col, Button.from_dict(row, col, button_data))
    save_deck(deck, deck.path)
    return _deck_summary(deck)


# ── Buttons ──

@mcp.tool
def set_button(
    deck_id: str,
    row: Row,
    col: Col,
    label: str = "",
    behavior: Literal["single", "toggle"] = "single",
    command: Annotated[str, "For behavior='single'"] = "",
    on_command: Annotated[str, "For behavior='toggle'"] = "",
    off_command: Annotated[str, "For behavior='toggle'"] = "",
    state: Literal["off", "on"] = "off",
    icon: Annotated[Optional[str], "Relative asset path from import_icon"] = None,
) -> dict:
    """Create or replace the button at a position.

    Commands are run through a shell exactly as typed in a terminal.
    """
    deck = _find_deck(deck_id)
    _check_position(deck, row, col)

    button = Button(
        row=row, col=col, label=label,
        behavior=TOGGLE if behavior == "toggle" else SINGLE,
        command=command, on_command=on_command, off_command=off_command,
        state=state, icon=icon,
    )
    deck.place(row, col, button)
    save_deck(deck, deck.path)
    return _button_summary(button)


@mcp.tool
def get_button(deck_id: str, row: Row, col: Col) -> dict:
    """Read one button. Returns {'empty': true} if that key is unused."""
    deck = _find_deck(deck_id)
    _check_position(deck, row, col)
    button = deck.get(row, col)
    return _button_summary(button) if button else {"row": row, "col": col,
                                                   "empty": True}


@mcp.tool
def remove_button(deck_id: str, row: Row, col: Col) -> dict:
    """Clear one key."""
    deck = _find_deck(deck_id)
    _check_position(deck, row, col)
    button = deck.remove(row, col)
    if button is None:
        return {"removed": False, "reason": "that key was already empty"}
    save_deck(deck, deck.path)
    StateManager().forget_position(deck.deck_id, (row, col))
    return {"removed": True, "label": button.display_label()}


@mcp.tool
def move_button(deck_id: str, from_row: Row, from_col: Col,
                to_row: Row, to_col: Col) -> dict:
    """Move a button to another key, swapping if the target is occupied."""
    deck = _find_deck(deck_id)
    _check_position(deck, from_row, from_col)
    _check_position(deck, to_row, to_col)
    if deck.get(from_row, from_col) is None:
        raise ValueError(f"No button at ({from_row}, {from_col}).")
    deck.move((from_row, from_col), (to_row, to_col))
    save_deck(deck, deck.path)
    return get_deck(deck_id)


@mcp.tool
def clear_deck(deck_id: str) -> dict:
    """Remove every button from a deck, keeping the deck itself."""
    deck = _find_deck(deck_id)
    removed = len(deck.buttons)
    deck.buttons.clear()
    save_deck(deck, deck.path)
    StateManager().forget_deck(deck.deck_id)
    return {"deck_id": deck.deck_id, "removed_buttons": removed}


@mcp.tool
def press_button(deck_id: str, row: Row, col: Col,
                 timeout_seconds: int = 15) -> dict:
    """Run a button's command and report what happened.

    For a toggle this runs the command for its *next* press and flips the
    stored state, exactly as pressing the key in the app would.
    """
    deck = _find_deck(deck_id)
    _check_position(deck, row, col)
    button = deck.get(row, col)
    if button is None:
        raise ValueError(f"No button at ({row}, {col}).")

    manager = StateManager()
    if button.is_toggle:
        button.state = manager.get(deck.deck_id, (row, col), button.state)
    command = button.command_for_next_press()
    if not command.strip():
        return {"ran": False, "reason": "no command set for that press"}

    result = subprocess.run(["bash", "-c", command], capture_output=True,
                            text=True, timeout=timeout_seconds)

    if button.is_toggle:
        button.state = "off" if button.state == "on" else "on"
        manager.set(deck.deck_id, (row, col), button.state)

    return {
        "ran": True,
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "new_state": button.state if button.is_toggle else None,
    }


@mcp.tool
def find_buttons(
    query: Annotated[str, "Matched against button labels and commands"],
) -> list[dict]:
    """Search every deck for buttons whose label or command matches."""
    needle = (query or "").strip().lower()
    if not needle:
        raise ValueError("Give something to search for.")

    decks, _errors = load_all_decks()
    hits = []
    for deck in decks:
        for (row, col), button in sorted(deck.buttons.items()):
            haystack = " ".join((button.label, button.command,
                                 button.on_command, button.off_command)).lower()
            if needle in haystack:
                hit = _button_summary(button)
                hit["deck_id"] = deck.deck_id
                hit["deck_name"] = deck.name
                hits.append(hit)
    return hits


@mcp.tool
def set_button_icon(deck_id: str, row: Row, col: Col,
                    image_path: Annotated[str, "Absolute path, or '' to clear"]
                    ) -> dict:
    """Import an image and put it on a button in one step."""
    deck = _find_deck(deck_id)
    _check_position(deck, row, col)
    button = deck.get(row, col)
    if button is None:
        raise ValueError(f"No button at ({row}, {col}).")

    if not image_path:
        button.icon = None
    else:
        button.icon = icon_store.import_icon(image_path)
    save_deck(deck, deck.path)

    result = _button_summary(button)
    if button.icon and icon_store.looks_opaque(button.icon):
        result["warning"] = ("That image has no transparent areas, so it will "
                             "show as a rectangle on the key.")
    return result


# ── Toggle state ──

@mcp.tool
def get_toggle_states(deck_id: str) -> dict:
    """The remembered on/off state of every toggle in a deck."""
    deck = _find_deck(deck_id)
    manager = StateManager()
    return {
        f"{row},{col}": manager.get(deck.deck_id, (row, col), button.state)
        for (row, col), button in sorted(deck.buttons.items())
        if button.is_toggle
    }


@mcp.tool
def set_toggle_state(deck_id: str, row: Row, col: Col,
                     state: Literal["on", "off"]) -> dict:
    """Set a toggle's remembered state without running any command."""
    deck = _find_deck(deck_id)
    _check_position(deck, row, col)
    button = deck.get(row, col)
    if button is None or not button.is_toggle:
        raise ValueError(f"({row}, {col}) is not a toggle button.")
    StateManager().set(deck.deck_id, (row, col), state)
    return {"deck_id": deck.deck_id, "row": row, "col": col, "state": state}


# ── Icons ──

@mcp.tool
def add_icon(image_path: Annotated[str, "Absolute path to a PNG/SVG/JPEG"]) -> dict:
    """Import an image into DeckApp's icon store and return the reference to
    pass to set_button(icon=...)."""
    relative = icon_store.import_icon(image_path)
    return {
        "icon": relative,
        "opaque": icon_store.looks_opaque(relative),
        "note": ("This image has no transparent areas, so it will show as a "
                 "rectangle on the key." if icon_store.looks_opaque(relative)
                 else "Has transparency, good for a key."),
    }


@mcp.tool
def list_icons() -> list[dict]:
    """Every icon in the store, and which buttons use it."""
    decks, _errors = load_all_decks()
    used: dict[str, list] = {}
    for deck in decks:
        for (row, col), button in deck.buttons.items():
            if button.icon:
                used.setdefault(button.icon, []).append(
                    f"{deck.deck_id}({row},{col})"
                )
    result = []
    for path in sorted(get_icons_dir().glob("*")):
        if path.name.startswith("."):
            continue
        relative = f"icons/{path.name}"
        result.append({"icon": relative, "bytes": path.stat().st_size,
                       "used_by": used.get(relative, [])})
    return result


@mcp.tool
def remove_unused_icons() -> dict:
    """Delete icon files no deck references."""
    decks, _errors = load_all_decks()
    used = set()
    for deck in decks:
        used |= deck.used_icons()
    return {"removed": icon_store.prune_unused_icons(used)}


# ── The running app ──

@mcp.tool
def open_deck_window(deck_id: str) -> dict:
    """Open a deck as a pad window on screen. Starts DeckApp if it is not
    running; if it is, the running instance opens the pad."""
    deck = _find_deck(deck_id)
    _run_cli("--deck", deck.deck_id)
    return {"opened": deck.deck_id}


@mcp.tool
def app_version() -> dict:
    """DeckApp's version and where it is installed."""
    import deckapp
    return {"version": deckapp.__version__,
            "package": str(Path(deckapp.__file__).parent)}


@mcp.tool
def app_status() -> dict:
    """Whether DeckApp is running, and how it is configured."""
    from deckapp.core import autostart

    try:
        owner = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
             "--object-path", "/org/freedesktop/DBus", "--method",
             "org.freedesktop.DBus.NameHasOwner",
             "io.github.prabhatm021.deckapp"],
            capture_output=True, text=True, timeout=5).stdout
        running = "true" in owner
    except Exception:
        running = False

    return {
        "running": running,
        "run_in_background": prefs.get_run_in_background(),
        "starts_on_login": autostart.is_enabled(),
        "decks_folder": str(get_decks_dir()),
        "deck_count": len(list_deck_paths()),
    }


# ── Resources ──

@mcp.resource("deckapp://decks")
def decks_resource() -> str:
    """All decks as JSON."""
    return json.dumps(list_decks(), indent=2)


@mcp.resource("deckapp://deck/{deck_id}")
def deck_resource(deck_id: str) -> str:
    """One deck as JSON, buttons included."""
    return json.dumps(get_deck(deck_id), indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
