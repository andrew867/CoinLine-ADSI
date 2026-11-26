"""Validation and interpretation shared by calls and the browser simulator."""

import asyncio
import json
import re
import textwrap
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator

from . import wire
from .link import Link


TOKEN = re.compile(r"\{\{([a-z][a-z0-9_-]*)\.([A-Za-z][A-Za-z0-9_]*)\}\}")
ARGUMENTS = {
    "weather.current": ({"site"}, set()),
    "weather.forecast": ({"site"}, set()),
    "news.headlines": ({"topic"}, set()),
    "market.quote": ({"instrument"}, set()),
    "lottery.draw": ({"game"}, {"draw_date"}),
    "assistant.answer": ({"question"}, set()),
    "airport.arrivals": ({"airport"}, set()),
    "airport.departures": ({"airport"}, set()),
    "directory.lookup": ({"number"}, set()),
    "cinema.showtimes": ({"selection"}, set()),
    "parcel.track": ({"number"}, set()),
    "travel.road": ({"selection"}, set()),
    "travel.events": ({"selection"}, set()),
    "travel.advisories": ({"selection"}, set()),
    "travel.ferries": ({"selection"}, set()),
    "weather.alerts": ({"selection"}, set()),
    "transit.bulletins": ({"selection"}, set()),
    "transit.departures": ({"selection"}, set()),
}
OUTPUTS = {
    "weather.current": {"place", "temperatureText", "localTime", "displayTitle", "source"},
    "weather.forecast": {"place", "forecast", "displayTitle", "source"},
    "news.headlines": {"headline", "localTime", "displayTitle", "source"},
    "market.quote": {"symbol", "priceText", "localTime", "delay", "displayTitle", "source"},
    "lottery.draw": {"game", "drawDate", "numbers", "bonus", "displayTitle", "source"},
    "assistant.answer": {"answer", "source", "displayTitle"},
    **{operation: {"displayTitle", "direction", "source", "updated", *(f"flight{i}" for i in range(1, 6))}
       for operation in ("airport.arrivals", "airport.departures")},
    "directory.lookup": {"name", "number", "detail", "source", "displayTitle"},
    "cinema.showtimes": {"displayTitle", "theatre", "movie", "date", "source", *(f"times{i}" for i in range(1, 7))},
    "parcel.track": {"displayTitle", "status", "updated", "estimate", "source"},
    **{operation: {"displayTitle", "subject", "status", "updated", "source", *(f"detail{i}" for i in range(1,7))}
       for operation in ("travel.road", "travel.events", "travel.advisories", "travel.ferries", "weather.alerts", "transit.bulletins")},
    "transit.departures": {"displayTitle", "stop", "source", "updated", *(f"departure{i}" for i in range(1,7))},
}


def _schema():
    root = Path(__file__).resolve().parents[1]
    path = root / "graph.schema.json"
    if not path.exists():
        path = root.parent / "docs/spec/graph.schema.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


VALIDATOR = _schema()


def choices(node: dict) -> list[dict]:
    if node["type"] == "menu":
        return node["choices"]
    if node["type"] == "message":
        return [node["continue"]]
    return []


def edges(node: dict) -> list[str]:
    match node["type"]:
        case "provider":
            return [node["onOk"], node["onUnavailable"]]
        case "menu" | "message":
            return [node["onTimeout"], *(choice["target"] for choice in choices(node))]
        case _:
            return []


def validate(graph: dict) -> list[dict]:
    errors = [{"path": "/".join(map(str, error.absolute_path)), "message": error.message}
              for error in VALIDATOR.iter_errors(graph)]
    if errors:
        return errors[:20]
    nodes = {node["id"]: node for node in graph["nodes"]}
    entry = graph["entry"]
    if entry not in nodes or len(nodes) != len(graph["nodes"]):
        return [{"path": "nodes", "message": "The entry must exist and node IDs must be unique."}]

    def issue(node, message):
        errors.append({"path": node["id"], "message": message})

    bindings = {}
    for node in nodes.values():
        if node["type"] == "provider":
            required, optional = ARGUMENTS[node["operation"]]
            args = set(node["args"])
            if not required <= args <= required | optional:
                issue(node, "Provider arguments do not match the selected operation.")
            if node["bind"] in bindings:
                issue(node, "Provider binding is already defined.")
            bindings[node["bind"]] = OUTPUTS[node["operation"]]
    for node in nodes.values():
        if any(edge not in nodes for edge in edges(node)):
            issue(node, "All transitions must reference existing nodes.")
        digits = [choice["digit"] for choice in choices(node)]
        if len(digits) != len(set(digits)):
            issue(node, "Menu digits must be unique.")
        if any(not handset_text(choice["label"]) for choice in choices(node)):
            issue(node, "Each choice needs a printable handset label.")
        text = [node.get("prompt", ""), *node.get("lines", [])]
        for template in text:
            if any(field not in bindings.get(binding, set()) for binding, field in TOKEN.findall(template)):
                issue(node, "Template references an unknown provider field.")
            if "{{" in TOKEN.sub("", template) or "}}" in TOKEN.sub("", template):
                issue(node, "Template syntax is invalid.")
        if node["type"] in ("menu", "message") and not any(TOKEN.search(line) for line in node["lines"]):
            if len(screen_pages(node, node["lines"])) > 1 and len(digits) > 4:
                issue(node, "A paged screen can use up to four choices.")
    if errors:
        return errors[:20]

    reachable = {entry}
    pending = [entry]
    while pending:
        for target in edges(nodes[pending.pop()]):
            if target not in reachable:
                pending.append(target)
                reachable.add(target)
    can_end = {node["id"] for node in nodes.values() if node["type"] == "end"}
    while True:
        previous = len(can_end)
        can_end.update(node["id"] for node in nodes.values() if any(edge in can_end for edge in edges(node)))
        if len(can_end) == previous:
            break
    for node in nodes.values():
        if node["id"] not in reachable or node["id"] not in can_end:
            issue(node, "Every node must be reachable and lead to an exit.")

    visiting, checked = set(), set()

    def automatic_cycle(identifier):
        if identifier in visiting:
            return True
        if identifier in checked or nodes[identifier]["type"] != "provider":
            return False
        visiting.add(identifier)
        found = any(automatic_cycle(target) for target in edges(nodes[identifier]))
        visiting.remove(identifier)
        checked.add(identifier)
        return found

    if any(automatic_cycle(identifier) for identifier in nodes):
        errors.append({"path": "nodes", "message": "Automatic transitions contain a cycle."})
    return errors[:20]


def handset_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return " ".join(normalized.encode("ascii", "ignore").decode().split())


def pages(lines: list[str]) -> list[list[str]]:
    wrapped = []
    for line in lines:
        wrapped.extend(textwrap.wrap(handset_text(line), width=20) or [" "])
    return [wrapped[index:index + 4] for index in range(0, len(wrapped), 4)]


def screen_pages(node: dict, lines: list[str]) -> list[list[str]]:
    """Information screens retain their title and show page progress, without empty data rows."""
    if node.get("layout") != "information":
        return pages(lines)
    rows = [row for line in lines for row in textwrap.wrap(handset_text(line), width=20)]
    if not rows:
        return [["Unavailable"]]
    if len(rows) <= 4:
        return [rows]
    title, body = rows[0], rows[1:]
    count = (len(body) + 1) // 2
    return [[title, *body[i:i+2], *([" "] if len(body[i:i+2]) == 1 else []), f"Page {i//2+1}/{count}"]
            for i in range(0, len(body), 2)]


Lookup = Callable[[str, dict[str, str]], Awaitable[dict[str, str] | None]]


@dataclass
class Session:
    graph: dict
    node: str = field(init=False)
    index: int = 0
    steps: int = 0
    values: dict = field(default_factory=dict)
    trace: list = field(default_factory=list)
    ended: bool = False

    def __post_init__(self):
        self.nodes = {node["id"]: node for node in self.graph["nodes"]}
        self.node = self.graph["entry"]

    def _move(self, identifier: str) -> None:
        if self.steps >= 512:
            self.ended = True
            return
        self.trace.append(self.node)
        self.node = identifier
        self.index = 0
        self.steps += 1

    def _format(self, template: str) -> str:
        return TOKEN.sub(lambda match: str(self.values.get(match[1], {}).get(match[2], ""))[:160], template)

    async def settle(self, lookup: Lookup, prepare=None, provider_timeout=2) -> dict:
        for _ in range(32):
            current = self.nodes[self.node]
            if current["type"] != "provider" or self.ended:
                return self.view()
            arguments = current["args"] if prepare is None else await prepare(current["operation"], current["args"])
            result = None
            if arguments is not None:
                try:
                    timeout = (20 if current["operation"] in ("cinema.showtimes", "parcel.track", "weather.alerts") or
                               current["operation"].startswith(("travel.", "transit.")) else
                               12 if current["operation"].startswith("airport.") else
                               5 if current["operation"] == "assistant.answer" else provider_timeout)
                    async with asyncio.timeout(timeout):
                        result = await lookup(current["operation"], arguments)
                except TimeoutError:
                    pass
            if result is None:
                self.values.pop(current["bind"], None)
                self._move(current["onUnavailable"])
            else:
                self.values[current["bind"]] = result
                self._move(current["onOk"])
        self.ended = True
        return self.view()

    def view(self) -> dict:
        current = self.nodes[self.node]
        prompt = self._format(current.get("prompt", ""))
        if current["type"] == "end" or self.ended:
            return {"node": self.node, "lines": [], "choices": [], "prompt": prompt, "ended": True}
        screens = screen_pages(current, [self._format(line) for line in current.get("lines", [])]) or [["Unavailable"]]
        options = [{"digit": item["digit"], "label": handset_text(item["label"])[:7]} for item in choices(current)]
        if len(screens) > 1:
            if len(options) > 4:
                return {"node": self.node, "lines": ["Screen unavailable"], "choices": [],
                        "prompt": "This screen is unavailable.", "ended": True}
            if self.index > 0:
                options.append({"digit": "7", "label": "Prev"})
            if self.index + 1 < len(screens):
                options.append({"digit": "9", "label": "Next"})
        if current.get("layout") == "information" and len(options) <= 6:
            # Keep paging and return keys in fixed positions. The viewport never lists them.
            ordinary_slots = iter((1, 2, 3, 6) if len(screens) > 1 else range(1, 7))
            for option in options:
                if option["digit"] == "7":
                    option["slot"] = 4
                elif option["digit"] == "9":
                    option["slot"] = 5
                elif option["digit"] == "0":
                    option["slot"] = 6
                else:
                    option["slot"] = next(ordinary_slots)
            if len({option["slot"] for option in options}) != len(options):
                for option in options:
                    option.pop("slot", None)
        return {"node": self.node, "lines": screens[self.index], "choices": options, "prompt": prompt,
                "page": self.index + 1, "pageCount": len(screens), "ended": False}

    def choose(self, digit: str) -> bool:
        current = self.nodes[self.node]
        view = self.view()
        if digit in ("7", "9") and any(item["digit"] == digit for item in view["choices"]):
            self.index += 1 if digit == "9" else -1
            return True
        for choice in choices(current):
            if choice["digit"] == digit:
                self._move(choice["target"])
                return True
        return False

    def timeout(self) -> None:
        target = self.nodes[self.node].get("onTimeout")
        if target:
            self._move(target)
        else:
            self.ended = True


async def run_call(graph: dict, lookup: Lookup, link: Link, say, prepare=None, provider_timeout=2, handoff=None):
    session = Session(graph)
    display = await link.connect()
    while True:
        view = await session.settle(lookup, prepare, provider_timeout)
        if view["ended"]:
            if handoff and not session.ended and await handoff(session.nodes[session.node]):
                return
            await link.release()
            if view["prompt"]:
                await say(view["prompt"])
            return
        if display:
            await link.transfer(wire.screen(view["lines"], [(item["label"], item["digit"])
                                                             for item in view["choices"]],
                                            slots=[item.get("slot", index + 1) for index, item in enumerate(view["choices"])]), open_input=True)
        else:
            navigation = {"7": "Press seven for the previous page.", "9": "Press nine for the next page."}
            link.open_voice_input()
            if session.nodes[session.node].get("layout") == "information" and view["pageCount"] > 1:
                await say(". ".join([*view["lines"], *(navigation.get(item["digit"]) or
                    f"Press {item['digit']} for {item['label']}" for item in view["choices"])]))
            else:
                await say(" ".join([view["prompt"], *(navigation.get(item["digit"], "") for item in view["choices"])]))
        deadline = asyncio.get_running_loop().time() + 60
        try:
            while not session.choose(await link.selection(max(0, deadline - asyncio.get_running_loop().time()))):
                pass
        except TimeoutError:
            session.timeout()
