"""Translate a foreign VLN model's discrete action token into the exact
natural-language phrase NaVILA's round_trip_eval.py::parse_vlm_command /
get_vel_command (omni.isaac.vlnce.utils.eval_utils) recognizes via substring
match, so the Isaac Sim harness can stay completely unmodified.

Recognized phrases (must match get_vel_command's substring checks exactly):
  "turn left 15 degrees"
  "turn right 15 degrees"
  "move forward 25 cm"
  "stop"

get_vel_command has a silent fallback: any text it does NOT recognize as
turn/move/stop is executed as "move forward" anyway. That is dangerous for
an adapter (a translation bug would silently become blind forward motion),
so this module never returns free text -- it only ever returns one of the
four fixed phrases above, and raises instead of guessing on unknown input.
"""

FORWARD = "move forward 25 cm"
TURN_LEFT = "turn left 15 degrees"
TURN_RIGHT = "turn right 15 degrees"
STOP = "stop"


class UnknownActionTokenError(ValueError):
    pass


def translate_streamvln_action(action_id):
    """StreamVLN's VLNEvaluator.step() returns a list of ints from
    actions2idx = {STOP:[0], up:[1], left:[2], right:[3]}. This function
    translates a single action id (the caller picks which step of the
    predicted sequence to use -- see streamvln_server.py)."""
    mapping = {0: STOP, 1: FORWARD, 2: TURN_LEFT, 3: TURN_RIGHT}
    try:
        return mapping[int(action_id)]
    except (KeyError, TypeError, ValueError):
        raise UnknownActionTokenError(f"StreamVLN action id: {action_id!r}")


def translate_uninavid_action(action_word):
    """Uni-NaVid's agent.act() returns action_list = navigation.split(' ')
    with words from {'forward','left','right','stop'} (see
    offline_eval_uninavid.py). Translates a single word (the caller picks
    which step of the predicted sequence to use -- see uninavid_server.py)."""
    mapping = {
        "forward": FORWARD,
        "left": TURN_LEFT,
        "right": TURN_RIGHT,
        "stop": STOP,
    }
    key = str(action_word).strip().lower()
    if key not in mapping:
        raise UnknownActionTokenError(f"Uni-NaVid action word: {action_word!r}")
    return mapping[key]


if __name__ == "__main__":
    # Pure-python self-test, no model/GPU involved.
    assert translate_streamvln_action(0) == STOP
    assert translate_streamvln_action(1) == FORWARD
    assert translate_streamvln_action(2) == TURN_LEFT
    assert translate_streamvln_action(3) == TURN_RIGHT
    for bad in (4, -1, "x", None):
        try:
            translate_streamvln_action(bad)
            raise AssertionError(f"expected UnknownActionTokenError for {bad!r}")
        except UnknownActionTokenError:
            pass

    assert translate_uninavid_action("forward") == FORWARD
    assert translate_uninavid_action("left") == TURN_LEFT
    assert translate_uninavid_action("right") == TURN_RIGHT
    assert translate_uninavid_action("stop") == STOP
    assert translate_uninavid_action("STOP") == STOP  # case-insensitive
    for bad in ("backward", "", None, "forward "):
        # note: "forward " has trailing space, still valid after strip()
        if bad == "forward ":
            assert translate_uninavid_action(bad) == FORWARD
            continue
        try:
            translate_uninavid_action(bad)
            raise AssertionError(f"expected UnknownActionTokenError for {bad!r}")
        except UnknownActionTokenError:
            pass

    # Confirm every returned phrase is recognized the same way
    # get_vel_command's substring matching recognizes it, replicated here
    # verbatim from eval_utils.py so a wording drift breaks this test loudly.
    def get_vel_command_like(text):
        t = text.lower()
        if "turn left" in t:
            return "left"
        if "turn right" in t:
            return "right"
        if "move forward" in t or "move" in t:
            return "forward"
        if "stop" in t:
            return "stop"
        return "UNRECOGNIZED_FALLS_THROUGH_TO_FORWARD"

    assert get_vel_command_like(FORWARD) == "forward"
    assert get_vel_command_like(TURN_LEFT) == "left"
    assert get_vel_command_like(TURN_RIGHT) == "right"
    assert get_vel_command_like(STOP) == "stop"

    print("nav_action_translate self-test: all checks passed")
