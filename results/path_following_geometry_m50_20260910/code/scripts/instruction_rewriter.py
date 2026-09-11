"""Generate deterministic outbound and return instructions for round-trip VLN."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


PROMPT_VERSION = "round-trip-rewriter-v4"

# Step 1 — ask the LLM to parse the outbound instruction into atomic steps.
PARSE_PROMPT = """Parse a navigation instruction into a sequence of atomic steps as JSON.

Schema:
{"steps": [{"type": <type>, "direction": <dir_or_null>, "landmark": <text_or_null>}]}

Step types:
  "exit_room"   – leaving a named room or space
  "enter_room"  – entering a named room or space
  "turn"        – a change in heading
  "move"        – forward motion, optionally past a landmark
  "stop"        – the final stopping action

Directions: "left", "right", "straight", or null.

Rules:
- Copy all landmark text verbatim from the source. Do not paraphrase.
- Do not add steps that are not stated in the source.
- Examples:
    "exit the bedroom and turn left" ->
      [{"type":"exit_room","landmark":"bedroom","direction":null},
       {"type":"turn","landmark":null,"direction":"left"}]
    "walk straight passing the gray couch" ->
      [{"type":"move","landmark":"gray couch","direction":"straight"}]
    "stop near the rug" ->
      [{"type":"stop","landmark":"rug","direction":null}]
Return JSON only."""

# Step 3 — ask the LLM to render the mechanically-inverted steps back to natural language.
RENDER_PROMPT = """Convert a sequence of navigation steps into a single VLN-style instruction.

Rules:
- Write one clause per step, joined naturally.
- Prefer concise, executable navigation language such as "walk straight into the hallway",
  "turn right", "go into the room", and "wait near the door".
- Avoid meta-task wording such as "return phase", "original starting location", or
  "retrace the route".
- Avoid opening with "From the <landmark>" unless it is necessary for disambiguation.
- The final step of type "stop" should become a visible stopping target when possible,
  for example "wait near the door on the left".
- Do not add distances, degree values, or spatial detail not present in the steps.
- Match the style and sentence length of a typical navigation instruction.

Example:
Outbound source: Exit the bedroom and turn left. Walk straight passing the gray couch and stop near the rug.
Weak reverse: From the rug, move straight to the gray couch, turn right, and enter the bedroom.
Better reverse: Walk straight into the hallway. Turn right and go into the room. Wait near the door on the left.

Return JSON only: {"instruction": "..."}"""

_DIRECTION_INVERSE: dict[str | None, str | None] = {
    "left": "right",
    "right": "left",
    "straight": "straight",
    "forward": "forward",
    None: None,
}
_TYPE_INVERSE: dict[str, str] = {
    "exit_room": "enter_room",
    "enter_room": "exit_room",
}


def _invert_steps(steps: list[dict]) -> list[dict]:
    """Mechanically reverse and invert a parsed step list.

    This function is deterministic — it applies fixed rules and never calls an LLM.
    """
    steps = [copy.copy(s) for s in steps]

    # The final stop step provides the start context ("From the <landmark>") for the return.
    start_landmark: str | None = None
    if steps and steps[-1]["type"] == "stop":
        start_landmark = steps[-1].get("landmark")
        steps = steps[:-1]

    # The first exit_room step tells us where the agent originally started.
    end_landmark = "original starting location"
    for step in steps:
        if step["type"] == "exit_room" and step.get("landmark"):
            end_landmark = step["landmark"]
            break

    # Reverse step order and apply per-step inversions.
    inverted: list[dict] = []
    for step in reversed(steps):
        s = copy.copy(step)
        s["direction"] = _DIRECTION_INVERSE.get(s.get("direction"), s.get("direction"))
        s["type"] = _TYPE_INVERSE.get(s["type"], s["type"])
        inverted.append(s)

    result: list[dict] = []
    if start_landmark:
        result.append({"type": "start_from", "landmark": start_landmark, "direction": None})
    result.extend(inverted)
    result.append({"type": "stop", "landmark": end_landmark, "direction": None})
    return result


@dataclass(frozen=True)
class RoundTripInstructions:
    source_instruction: str
    outbound_instruction: str
    return_instruction: str
    round_trip_instruction: str
    provider: str
    model: str
    prompt_version: str = PROMPT_VERSION


class InstructionRewriteError(RuntimeError):
    """Raised when a return instruction cannot be generated or validated."""


def _normalize(text: str) -> str:
    return " ".join(str(text).strip().split())


def _cache_key(source_instruction: str) -> str:
    payload = {
        "source_instruction": _normalize(source_instruction),
        "prompt_version": PROMPT_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _extract_json(text: str) -> dict:
    cleaned = str(text).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise InstructionRewriteError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise InstructionRewriteError("LLM response must be a JSON object")
    return value


def _validate_return_instruction(source: str, return_instruction: str) -> str:
    source = _normalize(source)
    result = _normalize(return_instruction)
    if len(result) < 20:
        raise InstructionRewriteError("Generated return instruction is too short")
    if result.casefold() == source.casefold():
        raise InstructionRewriteError("Generated return instruction matches the outbound instruction")
    if result.casefold().startswith(("stop ", "stop.", "stop,")):
        raise InstructionRewriteError("Generated return instruction repeats the outbound stop as its first action")
    if any(token in result.casefold() for token in ("as an ai", "cannot determine", "not enough information")):
        raise InstructionRewriteError("Generated return instruction contains a refusal")
    return result


def _compose(source: str, return_instruction: str, provider: str, model: str) -> RoundTripInstructions:
    source = _normalize(source)
    outbound = (
        f"{source} This is the outbound phase of a round-trip task. "
        "Stop at the described destination before beginning the return."
    )
    return_phase = return_instruction
    combined = (
        f"Outbound: {source} After reaching the outbound destination, stop and confirm it. "
        f"Return: {return_instruction} Stop when you reach the original starting location."
    )
    return RoundTripInstructions(
        source_instruction=source,
        outbound_instruction=outbound,
        return_instruction=return_phase,
        round_trip_instruction=combined,
        provider=provider,
        model=model,
    )


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise InstructionRewriteError(f"Instruction LLM request failed: {exc}") from exc


def _ollama_completion(source: str, system_prompt: str, endpoint: str, model: str, timeout: float) -> str:
    response = _post_json(
        endpoint.rstrip("/") + "/api/chat",
        {
            "model": model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "seed": 0},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": source},
            ],
        },
        {},
        timeout,
    )
    try:
        return response["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise InstructionRewriteError("Unexpected Ollama response format") from exc


def _openai_compatible_completion(
    source: str,
    system_prompt: str,
    endpoint: str,
    model: str,
    api_key: str | None,
    timeout: float,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = _post_json(
        endpoint.rstrip("/") + "/v1/chat/completions",
        {
            "model": model,
            "temperature": 0,
            "seed": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": source},
            ],
        },
        headers,
        timeout,
    )
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise InstructionRewriteError("Unexpected OpenAI-compatible response format") from exc


def _episode_instruction(episode: dict) -> str:
    instruction = episode.get("instruction", {})
    if isinstance(instruction, dict):
        return _normalize(instruction.get("instruction_text", ""))
    return _normalize(instruction)


def _scene_key(episode: dict) -> str:
    scene_id = str(episode.get("scene_id", ""))
    return os.path.splitext(os.path.basename(scene_id))[0]


def _path_xy(episode: dict) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in episode.get("reference_path", [])]


def _point_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _ordered_path_match(
    candidate_path: list[tuple[float, float]],
    target_path: list[tuple[float, float]],
    tolerance_m: float,
) -> tuple[int, float]:
    """Return ordered match count and mean matched distance."""
    if not candidate_path or not target_path:
        return 0, float("inf")

    target_index = 0
    distances: list[float] = []
    for point in candidate_path:
        best_index = None
        best_distance = float("inf")
        for idx in range(target_index, len(target_path)):
            distance = _point_dist(point, target_path[idx])
            if distance < best_distance:
                best_index = idx
                best_distance = distance
        if best_index is not None and best_distance <= tolerance_m:
            distances.append(best_distance)
            target_index = best_index + 1
    if not distances:
        return 0, float("inf")
    return len(distances), sum(distances) / len(distances)


def _return_target_paths(source_episode: dict) -> list[list[tuple[float, float]]]:
    path = _path_xy(source_episode)
    if len(path) < 2:
        return []

    targets = [list(reversed(path))]
    # Many VLN-CE-Isaac reverse-direction episodes begin at the last interior
    # waypoint rather than the outbound goal disk center, so include this variant.
    if len(path) > 2:
        targets.append(list(reversed(path[:-1])))
    return targets


def _find_reverse_path_neighbor(
    dataset_path: str | os.PathLike[str],
    episode_index: int,
    tolerance_m: float = 2.0,
) -> tuple[dict, int, dict] | None:
    with gzip.open(dataset_path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    episodes = data["episodes"] if isinstance(data, dict) else data
    source_episode = episodes[episode_index]
    source_scene = _scene_key(source_episode)
    target_paths = _return_target_paths(source_episode)
    if not target_paths:
        return None

    best = None
    for idx, candidate in enumerate(episodes):
        if idx == episode_index or _scene_key(candidate) != source_scene:
            continue
        instruction = _episode_instruction(candidate)
        if not instruction:
            continue
        candidate_path = _path_xy(candidate)
        if len(candidate_path) < 2:
            continue

        for target_path in target_paths:
            matched, mean_distance = _ordered_path_match(candidate_path, target_path, tolerance_m)
            required = max(2, min(len(candidate_path), len(target_path)) - 1)
            coverage = matched / max(1, min(len(candidate_path), len(target_path)))
            if matched < required or coverage < 0.8:
                continue
            extra_waypoints = abs(len(candidate_path) - len(target_path))
            candidate_coverage = matched / max(1, len(candidate_path))
            key = (-matched, extra_waypoints, -candidate_coverage, mean_distance, idx)
            if best is None or key < best[0]:
                best = (key, candidate, idx, {
                    "matched_waypoints": matched,
                    "candidate_waypoints": len(candidate_path),
                    "target_waypoints": len(target_path),
                    "coverage": coverage,
                    "mean_distance_m": mean_distance,
                    "tolerance_m": tolerance_m,
                })

    if best is None:
        return None
    _, candidate, idx, metadata = best
    return candidate, idx, metadata


class InstructionRewriter:
    """Parse → mechanically invert → render pipeline for round-trip VLN instructions.

    The LLM is used only for parsing (step 1) and natural-language rendering (step 3).
    The inversion logic (step 2) is deterministic Python — landmark order, turn
    directions, and enter/exit inversions are applied by code, not by the model.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        cache_path: str | os.PathLike[str],
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        completion_fn: Callable[[str, str], str] | None = None,
        dataset_path: str | os.PathLike[str] | None = None,
        episode_index: int | None = None,
        neighbor_tolerance_m: float = 2.0,
    ):
        self.provider = provider
        self.model = model
        self.cache_path = Path(cache_path)
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        self.completion_fn = completion_fn
        self.dataset_path = Path(dataset_path) if dataset_path is not None else None
        self.episode_index = episode_index
        self.neighbor_tolerance_m = neighbor_tolerance_m

    def rewrite(self, source_instruction: str) -> RoundTripInstructions:
        source = _normalize(source_instruction)
        if not source:
            raise InstructionRewriteError("Outbound instruction is empty")

        cache = self._read_cache()
        key = _cache_key(source)
        cached = cache.get(key)
        if cached:
            return RoundTripInstructions(**cached)

        retrieved = self._retrieve_reverse_neighbor(source)
        if retrieved is not None:
            result = retrieved
            cache[key] = asdict(result)
            self._write_cache(cache)
            return result

        if self.provider == "cache_only":
            raise InstructionRewriteError(
                f"No cached reverse instruction for: {source!r}. "
                "Run instruction_rewriter.py with an LLM provider first, or provide dataset context "
                "so a reverse-path neighbor can be retrieved."
            )

        steps = self._parse_to_steps(source)
        inverted = _invert_steps(steps)
        raw_return = self._render_from_steps(inverted)
        reverse = _validate_return_instruction(source, raw_return)
        result = _compose(source, reverse, self.provider, self.model)
        cache[key] = asdict(result)
        self._write_cache(cache)
        return result

    def _retrieve_reverse_neighbor(self, source: str) -> RoundTripInstructions | None:
        if self.dataset_path is None or self.episode_index is None:
            return None
        match = _find_reverse_path_neighbor(
            self.dataset_path,
            self.episode_index,
            tolerance_m=self.neighbor_tolerance_m,
        )
        if match is None:
            return None
        candidate, candidate_index, metadata = match
        reverse = _validate_return_instruction(source, _episode_instruction(candidate))
        episode_id = candidate.get("episode_id", candidate_index)
        result = _compose(
            source,
            reverse,
            provider="dataset_reverse_path_neighbor",
            model=f"episode_index={candidate_index};episode_id={episode_id}",
        )
        # Store retrieval metadata in model for compatibility with the existing dataclass/cache schema.
        object.__setattr__(
            result,
            "model",
            f"episode_index={candidate_index};episode_id={episode_id};"
            f"matched_waypoints={metadata['matched_waypoints']};"
            f"mean_distance_m={metadata['mean_distance_m']:.3f}",
        )
        return result

    def _parse_to_steps(self, source: str) -> list[dict]:
        raw = self._complete(f"Instruction to parse:\n{source}", PARSE_PROMPT)
        parsed = _extract_json(raw)
        steps = parsed.get("steps")
        if not isinstance(steps, list) or not steps:
            raise InstructionRewriteError("Parse step did not return a non-empty 'steps' list")
        return steps

    def _render_from_steps(self, steps: list[dict]) -> str:
        raw = self._complete(
            f"Steps to render:\n{json.dumps(steps, ensure_ascii=False)}",
            RENDER_PROMPT,
        )
        parsed = _extract_json(raw)
        instruction = parsed.get("instruction", "")
        if not isinstance(instruction, str) or not instruction.strip():
            raise InstructionRewriteError("Render step did not return an 'instruction' string")
        return instruction.strip()

    def _complete(self, source: str, system_prompt: str) -> str:
        if self.completion_fn is not None:
            return self.completion_fn(source, system_prompt)
        if self.provider == "ollama":
            return _ollama_completion(
                source,
                system_prompt,
                self.endpoint or "http://127.0.0.1:11434",
                self.model,
                self.timeout,
            )
        if self.provider == "openai_compatible":
            if not self.endpoint:
                raise InstructionRewriteError("--instruction-llm-endpoint is required")
            return _openai_compatible_completion(
                source,
                system_prompt,
                self.endpoint,
                self.model,
                self.api_key,
                self.timeout,
            )
        raise InstructionRewriteError(f"Unsupported provider: {self.provider}")

    def _read_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            with self.cache_path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise InstructionRewriteError(f"Cannot read instruction cache: {exc}") from exc
        if not isinstance(value, dict):
            raise InstructionRewriteError("Instruction cache must contain a JSON object")
        return value

    def _write_cache(self, cache: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=self.cache_path.parent,
            prefix=self.cache_path.name + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(cache, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temp_path, self.cache_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def _load_episode_instruction(dataset_path: str, episode_index: int) -> str:
    with gzip.open(dataset_path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    episodes = data["episodes"] if isinstance(data, dict) else data
    return episodes[episode_index]["instruction"]["instruction_text"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and cache a reversed VLN instruction.")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--instruction")
    source_group.add_argument("--dataset")
    parser.add_argument("--episode-index", type=int, default=0)
    parser.add_argument("--provider", choices=("cache_only", "ollama", "openai_compatible"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument(
        "--cache",
        default=str(Path(__file__).with_name("generated") / "reversed_instructions.json"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--neighbor-tolerance-m", type=float, default=2.0)
    args = parser.parse_args()

    source = args.instruction or _load_episode_instruction(args.dataset, args.episode_index)
    rewriter = InstructionRewriter(
        provider=args.provider,
        model=args.model,
        cache_path=args.cache,
        endpoint=args.endpoint,
        api_key=os.getenv(args.api_key_env),
        timeout=args.timeout,
        dataset_path=args.dataset,
        episode_index=args.episode_index if args.dataset else None,
        neighbor_tolerance_m=args.neighbor_tolerance_m,
    )
    print(json.dumps(asdict(rewriter.rewrite(source)), indent=2))


if __name__ == "__main__":
    main()
