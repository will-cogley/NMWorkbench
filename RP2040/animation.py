from servoclass import Servo
import time

current_pose = "pose_calibrate"
current_state = "state_startup"
animation_bool_a = False
animation_bool_b = False
last_toggle_a = time.ticks_ms()
last_toggle_b = time.ticks_ms()
new_state_flag = True

# ============================================================
# Speaking: left/right neck shaking (ROL / SERVO8)
#
# PCB V2 verified mapping:
#   ROL -> SERVO8 -> PCA CH9 -> neck left/right
# Center position is 90 degrees.
# ============================================================
SPEAKING_NECK_LEFT = 65
SPEAKING_NECK_RIGHT = 115
SPEAKING_NECK_INTERVAL_MS = 520
LISTENING_NECK_CENTER = 90

speaking_neck_side = False
last_speaking_neck_toggle = time.ticks_ms()

# ============================================================
# Ears: alternating motion in Speaking + slower in Listening
#
# Verified PCB V2 mapping:
#   EAR -> SERVO1 -> PCA CH0 -> right ear
#   EAL -> SERVO2 -> PCA CH1 -> left ear
#
# The ear servos are mounted as a mirror pair.
# Therefore use the SAME numeric command on both ears.
# The mirrored mechanics create the opposite/symmetric physical motion.
#
# Use only the common safe range of both original V1 servo limits:
#   EAL: 60..150
#   EAR: 30..120
# Common range: 60..120
# ============================================================

EAR_ANGLE_A = 70
EAR_ANGLE_B = 115

SPEAKING_EAR_INTERVAL_MS = 520
SPEAKING_EAR_MAX_SPEED = 300.0
SPEAKING_EAR_MAX_ACCEL = 700.0

LISTENING_EAR_INTERVAL_MS = 1350
LISTENING_EAR_MAX_SPEED = 90.0
LISTENING_EAR_MAX_ACCEL = 220.0

# ============================================================
# Expression tuning: HAPPY / SAD
#
# HAPPY:
#   - one-sided neck pose
#   - no blinking
#   - faster mirrored ear alternating
#
# SAD:
#   - neck pitch down
#   - no blinking
#   - half-closed eyelid
#   - both ears droop/back
#
# Other servo behavior starts from the existing neutral
# pose_stop_speaking baseline.
# ============================================================

HAPPY_NECK_SIDE_ANGLE = 70
HAPPY_EAR_INTERVAL_MS = 300
HAPPY_EAR_MAX_SPEED = 400.0
HAPPY_EAR_MAX_ACCEL = 900.0
HAPPY_LID_OPEN_ANGLE = 150

# Eyelid normal pose-transition tuning.
# The old 50000/50000 values made large state changes (e.g. sleep 30 ->
# listening 130) behave almost like an instantaneous jump.
# Blinks are unaffected because blink code uses set_immediate().
LID_POSE_MAX_SPEED = 180.0
LID_POSE_MAX_ACCEL = 600.0

# Reuse the already-tested mirrored ear travel.
HAPPY_EAR_ANGLE_A = EAR_ANGLE_A
HAPPY_EAR_ANGLE_B = EAR_ANGLE_B

# Current PIT range is 1..80. 75 gives a clear "head down" pose.
SAD_PITCH_ANGLE = 75
SAD_LID_ANGLE = 130

# Reuse the existing sleep-style drooped ear pose.
SAD_LEFT_EAR_ANGLE = 150
SAD_RIGHT_EAR_ANGLE = 30

happy_ear_side = False
last_happy_ear_toggle = time.ticks_ms()

speaking_ear_side = False
last_speaking_ear_toggle = time.ticks_ms()

listening_ear_side = False
last_listening_ear_toggle = time.ticks_ms()

# ============================================================
# Speaking mouth: smooth, slow random opening/closing
#
# Verified PCB V2 mapping:
#   MOU -> SERVO4 -> PCA CH3 -> mouth
#
# The mouth alternates between a random OPEN range and a random
# CLOSED range. Alternating the two ranges guarantees visible movement,
# while the exact angle and dwell time remain random.
# ============================================================

MOUTH_OPEN_MIN = 8
MOUTH_OPEN_MAX = 55

MOUTH_CLOSED_MIN = 105
MOUTH_CLOSED_MAX = 150

# Slow random cadence: centered around the Listening-ear interval (1350 ms).
# It remains random, but is no longer machine-gun fast.
MOUTH_INTERVAL_MIN_MS = 1100
MOUTH_INTERVAL_MAX_MS = 1600

# Use the SAME motion speed/acceleration as Listening ears.
# The existing Servo.update(dt) motion planner provides smooth
# acceleration/deceleration interpolation between random mouth targets.
SPEAKING_MOUTH_MAX_SPEED = LISTENING_EAR_MAX_SPEED
SPEAKING_MOUTH_MAX_ACCEL = LISTENING_EAR_MAX_ACCEL

# MOU is speech-owned:
# its continuous motion is controlled by the independent speech flag in main.py,
# not by the current emotional/expression state.
MOUTH_REST_ANGLE = 150

mouth_open_phase = True
last_mouth_toggle = time.ticks_ms()
next_mouth_interval_ms = MOUTH_INTERVAL_MIN_MS
mouth_runtime_active = False
mouth_current_target = float(MOUTH_REST_ANGLE)

# Tiny local PRNG so this file does not depend on random/urandom modules.
_rand_state = (time.ticks_us() ^ 0xA5366B4D) & 0xFFFFFFFF
if _rand_state == 0:
    _rand_state = 0x13579BDF


def _rand_u32():
    global _rand_state

    x = _rand_state
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= (x >> 17)
    x ^= (x << 5) & 0xFFFFFFFF

    _rand_state = x & 0xFFFFFFFF
    return _rand_state


def _randint(a, b):
    if b <= a:
        return int(a)

    return int(a + (_rand_u32() % (b - a + 1)))


def _schedule_next_mouth(now):
    global next_mouth_interval_ms
    global last_mouth_toggle

    next_mouth_interval_ms = _randint(
        MOUTH_INTERVAL_MIN_MS,
        MOUTH_INTERVAL_MAX_MS
    )
    last_mouth_toggle = now


def _set_random_mouth_target():
    global mouth_open_phase
    global mouth_current_target

    if mouth_open_phase:
        angle = _randint(
            MOUTH_OPEN_MIN,
            MOUTH_OPEN_MAX
        )
    else:
        angle = _randint(
            MOUTH_CLOSED_MIN,
            MOUTH_CLOSED_MAX
        )

    mouth_current_target = float(angle)
    servos["MOU"].set_target(mouth_current_target)
    mouth_open_phase = not mouth_open_phase


def update_speaking_mouth(now, speaking_active):
    """
    Independent mouth controller.

    This is intentionally separate from current_state / emotion.
    Once the ESP reports "speaking", MOU keeps opening/closing even if
    the current expression later becomes "sad" or "happy".

    When speaking ends, MOU returns to the normal closed/rest position once.
    """
    global mouth_runtime_active
    global mouth_open_phase
    global mouth_current_target

    speaking_active = bool(speaking_active)

    if speaking_active and not mouth_runtime_active:
        servos["MOU"].max_speed = SPEAKING_MOUTH_MAX_SPEED
        servos["MOU"].max_accel = SPEAKING_MOUTH_MAX_ACCEL

        mouth_open_phase = True
        _set_random_mouth_target()
        _schedule_next_mouth(now)

        mouth_runtime_active = True
        print("[MOUTH] SPEECH ON -> independent mouth animation started")

    elif not speaking_active and mouth_runtime_active:
        mouth_runtime_active = False
        mouth_current_target = float(MOUTH_REST_ANGLE)
        servos["MOU"].set_target(mouth_current_target)
        print("[MOUTH] SPEECH OFF -> mouth returning to rest")

    if not mouth_runtime_active:
        return

    # Re-assert the current speech-owned target every loop.
    # This makes MOU win over any pose applied by an emotion on the same loop.
    servos["MOU"].set_target(mouth_current_target)

    if time.ticks_diff(now, last_mouth_toggle) >= next_mouth_interval_ms:
        _set_random_mouth_target()
        _schedule_next_mouth(now)


# ============================================================
# Random blink - simple timer version
#
# This is the old commented main.py blink idea moved into animation.py,
# but corrected for PCB V2 and the measured eyelid range.
#
# Active only in:
#   speaking / listening / thinking
#
# Verified mapping:
#   LID -> SERVO3 -> PCA CH2 -> eyelid
#
# IMPORTANT:
# Blink commands use Servo.set_immediate(), so there is NO software
# speed/acceleration interpolation during the blink itself.
# ============================================================

BLINK_ALLOWED_STATES = (
    "speaking",
    "listening",
    "thinking",
)

BLINK_CLOSED_ANGLE = 105
BLINK_DEFAULT_OPEN_ANGLE = 150

# How long the close command is held before reopening.
BLINK_DURATION_MS = 120

# Random interval between blinks. This is independent of loop frequency.
BLINK_INTERVAL_MIN_MS = 2800
BLINK_INTERVAL_MAX_MS = 6500

blink_state = {
    "active": False,
    "start_time": 0,
    "restore_angle": float(BLINK_DEFAULT_OPEN_ANGLE),
    "next_due": time.ticks_add(
        time.ticks_ms(),
        _randint(BLINK_INTERVAL_MIN_MS, BLINK_INTERVAL_MAX_MS)
    ),
}


def _schedule_next_blink(now):
    blink_state["next_due"] = time.ticks_add(
        now,
        _randint(
            BLINK_INTERVAL_MIN_MS,
            BLINK_INTERVAL_MAX_MS
        )
    )


def trigger_blink(now):
    """
    Start one blink.

    This is the useful part of the old commented main.py trigger_blink():
    remember the current eyelid expression, close once, then let
    update_blink() restore it after BLINK_DURATION_MS.
    """
    if blink_state["active"]:
        return

    lid = servos["LID"]
    current_target = float(lid.target)

    # Do not restore legacy unsafe low LID targets.
    if current_target <= BLINK_CLOSED_ANGLE + 5:
        restore_angle = float(BLINK_DEFAULT_OPEN_ANGLE)
    else:
        restore_angle = min(
            float(BLINK_DEFAULT_OPEN_ANGLE),
            current_target
        )

    blink_state["active"] = True
    blink_state["start_time"] = now
    blink_state["restore_angle"] = restore_angle

    # Immediate close: no interpolation/speed limiter.
    lid.set_immediate(BLINK_CLOSED_ANGLE)


def update_blink(now, state_name, enabled=True):
    """
    Non-blocking blink timer.

    Call once each main loop after apply_state().
    """
    allowed = (
        enabled
        and state_name in BLINK_ALLOWED_STATES
    )

    lid = servos["LID"]

    if not allowed:
        if blink_state["active"]:
            lid.set_immediate(
                blink_state["restore_angle"]
            )
            blink_state["active"] = False

        _schedule_next_blink(now)
        return

    # Finish the current blink exactly once.
    if blink_state["active"]:
        if (
            time.ticks_diff(
                now,
                blink_state["start_time"]
            )
            >= BLINK_DURATION_MS
        ):
            lid.set_immediate(
                blink_state["restore_angle"]
            )
            blink_state["active"] = False
            _schedule_next_blink(now)

        return

    # Start one random blink when its absolute due time arrives.
    if time.ticks_diff(
        now,
        blink_state["next_due"]
    ) >= 0:
        trigger_blink(now)


servos = {
    # PCB V2.0 compatibility mapping.
    # pin_num now means PHYSICAL SERVO SOCKET number, not RP2040 GPIO.
    "YAW": Servo(pin_num=9, max_speed=400, max_accel=100, min_angle=30, max_angle=150), # Base / body yaw
    "ROL": Servo(pin_num=8, max_speed=600, max_accel=400, min_angle=30, max_angle=120), # V2 neck left-right (legacy ROL name)
    "PIT": Servo(pin_num=7, max_speed=600, max_accel=400, min_angle=1, max_angle=80), # Neck pitch
    "MOU": Servo(pin_num=4, max_speed=50000, max_accel=10000, min_angle=5, max_angle=150), # Mouth
    "EYL": Servo(pin_num=6, max_speed=250, max_accel=10000, min_angle=50, max_angle=140), # Left eyeball
    "EYR": Servo(pin_num=5, max_speed=250, max_accel=10000, min_angle=50, max_angle=140), # Right eyeball
    "LID": Servo(pin_num=3, max_speed=LID_POSE_MAX_SPEED, max_accel=LID_POSE_MAX_ACCEL, min_angle=30, max_angle=160), # Eyelid
    "EAL": Servo(pin_num=2, max_speed=250, max_accel=200, min_angle=60, max_angle=150), # Left ear
    "EAR": Servo(pin_num=1, max_speed=500, max_accel=200, min_angle=30, max_angle=120), # Right ear
}

# ============================================================
# Explicit MCP actions
#
# These actions are intentionally separate from current_state/emotions.
# Each tool call performs exactly THREE complete cycles and temporarily owns
# every servo command so Speaking / random blink / Vision cannot move a second
# body part at the same time.
#
# Motion values are copied directly from the already-tested Speaking motion:
#   ROL: 65 <-> 115, 520 ms cadence, existing 600/400 speed/accel
#   ears: 70 <-> 115, 520 ms cadence, Speaking 300/700 speed/accel
# Blink reuses the existing tested LID close/open angles.
# ============================================================

MCP_ACTION_REPEAT_COUNT = 3
MCP_ACTION_INTERVAL_MS = SPEAKING_NECK_INTERVAL_MS
MCP_BLINK_OPEN_HOLD_MS = 180

MCP_ACTION_NAMES = (
    "shake_head",
    "blink",
    "left_ear",
    "right_ear",
    "ears",
)

mcp_action_queue = []
mcp_action_state = {
    "active": False,
    "name": None,
    "phase_b": False,
    "cycles": 0,
    "last_step": time.ticks_ms(),
    "final_wait": False,
    "blink_phase": None,
    "blink_restore": float(BLINK_DEFAULT_OPEN_ANGLE),
    "saved_tuning": {},
}


def queue_mcp_action(action_name):
    """Queue one explicit MCP action from ESP32 UART."""
    if action_name not in MCP_ACTION_NAMES:
        print("[MCP ACTION] unknown action:", action_name)
        return False

    # Keep a small queue so multiple sequential MCP calls are not lost if the
    # ESP sends the next command before the previous three-cycle animation ends.
    if len(mcp_action_queue) >= 8:
        print("[MCP ACTION] queue full, drop:", action_name)
        return False

    mcp_action_queue.append(action_name)
    print("[MCP ACTION] queued:", action_name)
    return True


def has_mcp_action():
    return mcp_action_state["active"] or bool(mcp_action_queue)


def cancel_mcp_actions():
    """Calibration safety path: cancel active and queued MCP motion."""
    global new_state_flag

    if mcp_action_state["active"]:
        _restore_mcp_action_tuning()

    mcp_action_state["active"] = False
    mcp_action_state["name"] = None
    mcp_action_state["final_wait"] = False
    mcp_action_state["blink_phase"] = None
    mcp_action_queue[:] = []
    new_state_flag = True


def _freeze_all_servos():
    """Stop every servo exactly where it is before a local MCP action."""
    for servo in servos.values():
        if servo.enabled:
            servo.set_immediate(servo.pos)


def _save_mcp_action_tuning(names):
    saved = {}
    for name in names:
        servo = servos[name]
        saved[name] = (
            float(servo.max_speed),
            float(servo.max_accel),
        )
    mcp_action_state["saved_tuning"] = saved


def _restore_mcp_action_tuning():
    for name, tuning in mcp_action_state["saved_tuning"].items():
        servo = servos[name]
        servo.max_speed = tuning[0]
        servo.max_accel = tuning[1]
    mcp_action_state["saved_tuning"] = {}


def _start_mcp_action(action_name, now):
    """Start one queued action. Called only when Calibration is not active."""
    global new_state_flag

    # If a random blink was in progress, end it before freezing the face.
    if blink_state["active"]:
        servos["LID"].set_immediate(blink_state["restore_angle"])
        blink_state["active"] = False
        _schedule_next_blink(now)

    # Preserve the normal open angle before freezing LID for an explicit blink.
    lid_target = float(servos["LID"].target)
    if lid_target <= BLINK_CLOSED_ANGLE + 5:
        blink_restore = float(BLINK_DEFAULT_OPEN_ANGLE)
    else:
        blink_restore = min(float(BLINK_DEFAULT_OPEN_ANGLE), lid_target)

    _freeze_all_servos()

    mcp_action_state["active"] = True
    mcp_action_state["name"] = action_name
    mcp_action_state["phase_b"] = False
    mcp_action_state["cycles"] = 0
    mcp_action_state["last_step"] = now
    mcp_action_state["final_wait"] = False
    mcp_action_state["blink_phase"] = None
    mcp_action_state["blink_restore"] = blink_restore
    mcp_action_state["saved_tuning"] = {}

    if action_name == "shake_head":
        _save_mcp_action_tuning(("ROL",))
        # Speaking does not override ROL tuning; these are the Servo defaults
        # used by Speaking on this project.
        servos["ROL"].max_speed = 600.0
        servos["ROL"].max_accel = 400.0
        servos["ROL"].set_target(SPEAKING_NECK_LEFT)

    elif action_name == "left_ear":
        _save_mcp_action_tuning(("EAL",))
        servos["EAL"].max_speed = SPEAKING_EAR_MAX_SPEED
        servos["EAL"].max_accel = SPEAKING_EAR_MAX_ACCEL
        servos["EAL"].set_target(EAR_ANGLE_A)

    elif action_name == "right_ear":
        _save_mcp_action_tuning(("EAR",))
        servos["EAR"].max_speed = SPEAKING_EAR_MAX_SPEED
        servos["EAR"].max_accel = SPEAKING_EAR_MAX_ACCEL
        servos["EAR"].set_target(EAR_ANGLE_A)

    elif action_name == "ears":
        _save_mcp_action_tuning(("EAL", "EAR"))
        servos["EAL"].max_speed = SPEAKING_EAR_MAX_SPEED
        servos["EAR"].max_speed = SPEAKING_EAR_MAX_SPEED
        servos["EAL"].max_accel = SPEAKING_EAR_MAX_ACCEL
        servos["EAR"].max_accel = SPEAKING_EAR_MAX_ACCEL
        # Same numeric command on the mirrored pair = opposite physical motion.
        servos["EAL"].set_target(EAR_ANGLE_A)
        servos["EAR"].set_target(EAR_ANGLE_A)

    elif action_name == "blink":
        # Reuse the existing blink geometry. Blink is intentionally immediate,
        # matching trigger_blink()/update_blink() already used by this firmware.
        servos["LID"].set_immediate(BLINK_CLOSED_ANGLE)
        mcp_action_state["blink_phase"] = "closed"

    # The current XiaoZhi state remains unchanged. It will be re-entered once
    # the MCP action has fully finished.
    new_state_flag = True
    print("[MCP ACTION] START:", action_name, "x", MCP_ACTION_REPEAT_COUNT)


def _movement_action_targets(action_name):
    if action_name == "shake_head":
        return ("ROL",)
    if action_name == "left_ear":
        return ("EAL",)
    if action_name == "right_ear":
        return ("EAR",)
    if action_name == "ears":
        return ("EAL", "EAR")
    return ()


def _movement_targets_settled(action_name):
    names = _movement_action_targets(action_name)
    if not names:
        return True

    for name in names:
        servo = servos[name]
        if abs(servo.target - servo.pos) > 1.0:
            return False
        if abs(servo.vel) > 2.0:
            return False
    return True


def _finish_mcp_action():
    global new_state_flag

    name = mcp_action_state["name"]
    _restore_mcp_action_tuning()
    mcp_action_state["active"] = False
    mcp_action_state["name"] = None
    mcp_action_state["final_wait"] = False
    mcp_action_state["blink_phase"] = None

    # Re-enter whatever state the ESP last requested (usually Speaking).
    new_state_flag = True
    print("[MCP ACTION] DONE:", name)


def _update_mcp_blink(now):
    phase = mcp_action_state["blink_phase"]
    elapsed = time.ticks_diff(now, mcp_action_state["last_step"])

    if phase == "closed":
        if elapsed < BLINK_DURATION_MS:
            return

        servos["LID"].set_immediate(mcp_action_state["blink_restore"])
        mcp_action_state["cycles"] += 1
        mcp_action_state["blink_phase"] = "open"
        mcp_action_state["last_step"] = now
        return

    if phase == "open":
        if elapsed < MCP_BLINK_OPEN_HOLD_MS:
            return

        if mcp_action_state["cycles"] >= MCP_ACTION_REPEAT_COUNT:
            _finish_mcp_action()
            return

        servos["LID"].set_immediate(BLINK_CLOSED_ANGLE)
        mcp_action_state["blink_phase"] = "closed"
        mcp_action_state["last_step"] = now


def _update_mcp_movement(now):
    action_name = mcp_action_state["name"]

    if mcp_action_state["final_wait"]:
        if _movement_targets_settled(action_name):
            _finish_mcp_action()
        return

    if time.ticks_diff(now, mcp_action_state["last_step"]) < MCP_ACTION_INTERVAL_MS:
        return

    mcp_action_state["phase_b"] = not mcp_action_state["phase_b"]
    phase_b = mcp_action_state["phase_b"]

    if action_name == "shake_head":
        target = SPEAKING_NECK_RIGHT if phase_b else SPEAKING_NECK_LEFT
        servos["ROL"].set_target(target)

    else:
        target = EAR_ANGLE_B if phase_b else EAR_ANGLE_A
        if action_name in ("left_ear", "ears"):
            servos["EAL"].set_target(target)
        if action_name in ("right_ear", "ears"):
            servos["EAR"].set_target(target)

    mcp_action_state["last_step"] = now

    # A complete cycle is A -> B -> A. Count only on the return to A.
    if not phase_b:
        mcp_action_state["cycles"] += 1
        if mcp_action_state["cycles"] >= MCP_ACTION_REPEAT_COUNT:
            mcp_action_state["final_wait"] = True


def update_mcp_action(now):
    """
    Advance explicit MCP motion once.

    Returns True while MCP owns the servos. main.py uses this to suppress
    Speaking, random blink, Vision and the independent speaking-mouth writer.
    """
    if not mcp_action_state["active"]:
        if not mcp_action_queue:
            return False

        action_name = mcp_action_queue.pop(0)
        _start_mcp_action(action_name, now)

    if mcp_action_state["name"] == "blink":
        _update_mcp_blink(now)
    else:
        _update_mcp_movement(now)

    # If one action ended and another is queued, retain ownership until the
    # next loop starts it. This prevents Speaking from moving between actions.
    return mcp_action_state["active"] or bool(mcp_action_queue)

def apply_pose(pose):
    pose = pose_map.get(pose, pose_calibrate)
    for name, angle in pose.items():
        if name in servos:
            servos[name].set_target(angle)
            
def apply_state(state_name):
    state_func = state_map.get(state_name)
    if state_func:
        state_func()  # Call the function
    else:
        print(f"Unknown state: {state_name}")
        
#_________________# Poses (static servo positions used in states) #_________________#

pose_calibrate = { # Each dictionary key = servo name, value = angle
    "YAW": 90,
    "ROL": 90,
    "PIT": 80,
    "MOU": 170,
    "LID": 110,
    "EYL": 90,
    "EYR": 90,
    "EAL": 90,
    "EAR": 90,
}
pose_sleep = { # Each dictionary key = servo name, value = angle
#     "YAW": 88,
#     "RWH": 89,
    "ROL": 90,
    "PIT": 80,
    "MOU": 170,
    "LID": 30,
#     "EYL": 90,
#     "EYR": 90,
    "EAL": 150,
    "EAR": 30,
}

pose_base = { # Each dictionary key = servo name, value = angle
#     "YAW": 88,
#     "RWH": 89,
    "ROL": 90,
#     "PIT": 20,
#     "MOU": 170,
    "LID": 150,
#     "EYL": 90,
#     "EYR": 90,
    "EAL": 130,
    "EAR": 70,
}

pose_speaking = { # Each dictionary key = servo name, value = angle
#     "YAW": 88,
#     "RWH": 89,
#     "ROL": 90,
#     "PIT": 20,
    "MOU": 10,
#     "LID": 130,
#     "EYL": 90,
#     "EYR": 90,
    "EAL": 130,
    "EAR": 70,
}

pose_stop_speaking = { # Each dictionary key = servo name, value = angle
#     "YAW": 88,
#     "RWH": 89,
#     "ROL": 90,
#     "PIT": 20,
    "MOU": 150,
#     "LID": 130,
#     "EYL": 90,
#     "EYR": 90,
    "EAL": 130,
    "EAR": 70,
}

pose_thinking_1 = { # Each dictionary key = servo name, value = angle
#     "YAW": 90,
#     "RWH": 90,
    "ROL": 130,
#     "PIT": 50,
    "MOU": 150,
    "LID": 70,
#     "EYL": 90,
#     "EYR": 90,
    "EAL": 150,
    "EAR": 120,
}

pose_curious_2 = { # Each dictionary key = servo name, value = angle
#     "YAW": 90,
#     "RWH": 90,
    "ROL": 40,
#     "PIT": 10,
    "MOU": 160,
    "LID": 130,
#     "EYL": 90,
#     "EYR": 90,
    "EAL": 60,
    "EAR": 60,
}

pose_map={
    "pose_calibrate": pose_calibrate,
    "pose_base": pose_base,
    "pose_thinking_1": pose_thinking_1,
    "pose_curious_2": pose_curious_2,
    "pose_sleep": pose_sleep,
    "pose_speaking": pose_speaking,
    "pose_stop_speaking": pose_stop_speaking,
}

#_________________#  #_________________#

#_________________# States (Mix of poses + animations) #_________________#



def state_startup():
    global new_state_flag
    if new_state_flag == True:
        apply_pose("pose_calibrate")
        new_state_flag = False

def state_sleep():
    global new_state_flag
    if new_state_flag == True:
        apply_pose("pose_sleep")
        new_state_flag = False
        
def state_speaking():
    global new_state_flag
    global speaking_neck_side
    global last_speaking_neck_toggle
    global speaking_ear_side
    global last_speaking_ear_toggle

    now = time.ticks_ms()

    if new_state_flag == True:
        apply_pose("pose_speaking")

        # Speaking: restore faster ear motion.
        servos["EAL"].max_speed = SPEAKING_EAR_MAX_SPEED
        servos["EAR"].max_speed = SPEAKING_EAR_MAX_SPEED
        servos["EAL"].max_accel = SPEAKING_EAR_MAX_ACCEL
        servos["EAR"].max_accel = SPEAKING_EAR_MAX_ACCEL

        # Start left/right neck shake from one side.
        speaking_neck_side = False
        last_speaking_neck_toggle = now
        servos["ROL"].set_target(SPEAKING_NECK_LEFT)

        # Start alternating mirrored ears.
        speaking_ear_side = False
        last_speaking_ear_toggle = now
        servos["EAL"].set_target(EAR_ANGLE_A)
        servos["EAR"].set_target(EAR_ANGLE_A)

        # MOU is handled independently by update_speaking_mouth().
        new_state_flag = False

    # Keep shaking the neck left/right for the whole speaking state.
    if time.ticks_diff(now, last_speaking_neck_toggle) >= SPEAKING_NECK_INTERVAL_MS:
        speaking_neck_side = not speaking_neck_side

        if speaking_neck_side:
            servos["ROL"].set_target(SPEAKING_NECK_RIGHT)
        else:
            servos["ROL"].set_target(SPEAKING_NECK_LEFT)

        last_speaking_neck_toggle = now

    # Speaking: ears alternate continuously at the faster rate.
    if time.ticks_diff(now, last_speaking_ear_toggle) >= SPEAKING_EAR_INTERVAL_MS:
        speaking_ear_side = not speaking_ear_side

        if speaking_ear_side:
            servos["EAL"].set_target(EAR_ANGLE_B)
            servos["EAR"].set_target(EAR_ANGLE_B)
        else:
            servos["EAL"].set_target(EAR_ANGLE_A)
            servos["EAR"].set_target(EAR_ANGLE_A)

        last_speaking_ear_toggle = now

def state_thinking():
    now=time.ticks_ms()
    global animation_bool_a, last_toggle_a, animation_bool_b, last_toggle_b, new_state_flag
    if new_state_flag == True:
        apply_pose("pose_base")
        new_state_flag = False
    if animation_bool_a == False:
        servos["PIT"].set_target(50)
    if animation_bool_a == True:
        servos["PIT"].set_target(120)
    if time.ticks_diff(now, last_toggle_a) >= 700:
        animation_bool_a = not animation_bool_a   # flip the boolean
        last_toggle_a = now
        
        
def state_listen():
    global new_state_flag
    global listening_ear_side
    global last_listening_ear_toggle

    now = time.ticks_ms()

    if new_state_flag == True:
        apply_pose("pose_curious_2")

        # Listening: left/right neck returns to center.
        servos["ROL"].set_target(LISTENING_NECK_CENTER)

        # Listening: same alternating ear gesture, but physically slower.
        servos["EAL"].max_speed = LISTENING_EAR_MAX_SPEED
        servos["EAR"].max_speed = LISTENING_EAR_MAX_SPEED
        servos["EAL"].max_accel = LISTENING_EAR_MAX_ACCEL
        servos["EAR"].max_accel = LISTENING_EAR_MAX_ACCEL

        listening_ear_side = False
        last_listening_ear_toggle = now
        servos["EAL"].set_target(EAR_ANGLE_A)
        servos["EAR"].set_target(EAR_ANGLE_A)

        new_state_flag = False

    # Listening: ears keep alternating, but much more slowly.
    if time.ticks_diff(now, last_listening_ear_toggle) >= LISTENING_EAR_INTERVAL_MS:
        listening_ear_side = not listening_ear_side

        if listening_ear_side:
            servos["EAL"].set_target(EAR_ANGLE_B)
            servos["EAR"].set_target(EAR_ANGLE_B)
        else:
            servos["EAL"].set_target(EAR_ANGLE_A)
            servos["EAR"].set_target(EAR_ANGLE_A)

        last_listening_ear_toggle = now

def state_neutral():
    global new_state_flag
    if new_state_flag == True:
        apply_pose("pose_stop_speaking")
        new_state_flag = False
        
def state_happy():
    """
    HAPPY expression overlay based on the current neutral baseline.

    Differences from neutral:
      - neck stays tilted/turned to one side
      - blinking is disabled because "happy" is not in BLINK_ALLOWED_STATES
      - mirrored ears alternate faster

    Unmentioned servos are left at the neutral pose_stop_speaking behavior.
    """
    global new_state_flag
    global happy_ear_side
    global last_happy_ear_toggle

    now = time.ticks_ms()

    if new_state_flag == True:
        # Start from the same baseline used by neutral.
        apply_pose("pose_stop_speaking")

        # One-sided neck pose: no left/right oscillation.
        servos["ROL"].set_target(HAPPY_NECK_SIDE_ANGLE)

        # Happy does not blink; keep eyelid fully open.
        servos["LID"].set_target(HAPPY_LID_OPEN_ANGLE)

        # Faster ear motion than speaking/listening.
        servos["EAL"].max_speed = HAPPY_EAR_MAX_SPEED
        servos["EAR"].max_speed = HAPPY_EAR_MAX_SPEED
        servos["EAL"].max_accel = HAPPY_EAR_MAX_ACCEL
        servos["EAR"].max_accel = HAPPY_EAR_MAX_ACCEL

        happy_ear_side = False
        last_happy_ear_toggle = now

        # Same numeric command on both mirrored ear servos.
        servos["EAL"].set_target(HAPPY_EAR_ANGLE_A)
        servos["EAR"].set_target(HAPPY_EAR_ANGLE_A)

        new_state_flag = False

    if time.ticks_diff(now, last_happy_ear_toggle) >= HAPPY_EAR_INTERVAL_MS:
        happy_ear_side = not happy_ear_side

        if happy_ear_side:
            ear_angle = HAPPY_EAR_ANGLE_B
        else:
            ear_angle = HAPPY_EAR_ANGLE_A

        servos["EAL"].set_target(ear_angle)
        servos["EAR"].set_target(ear_angle)

        last_happy_ear_toggle = now


def state_sad():
    """
    SAD expression overlay based on the current neutral baseline.

    Differences from neutral:
      - PIT holds a head-down angle
      - blinking is disabled because "sad" is not in BLINK_ALLOWED_STATES
      - eyelid stays half closed
      - ears stay drooped/back
      - MOU is deliberately NOT owned by SAD; speech controls it independently

    X visual tracking may still move the eyeballs/base; vision.py R17
    deliberately disables only Y->PIT tracking while SAD is active.
    """
    global new_state_flag

    if new_state_flag == True:
        # Start from the same baseline used by neutral.
        apply_pose("pose_stop_speaking")
        new_state_flag = False

    # Re-assert these expression-owned axes continuously.
    # This also guarantees SAD wins immediately after a state transition
    # that happened during a blink.
    servos["PIT"].set_target(SAD_PITCH_ANGLE)
    servos["LID"].set_target(SAD_LID_ANGLE)
    servos["EAL"].set_target(SAD_LEFT_EAR_ANGLE)
    servos["EAR"].set_target(SAD_RIGHT_EAR_ANGLE)


def state_limber_up():
    now=time.ticks_ms()
    global animation_bool_a, last_toggle_a, animation_bool_b, last_toggle_b, new_state_flag
    if new_state_flag == True:
        apply_pose("pose_base")
        new_state_flag = False
#     print("idle")
    if animation_bool_a == False:
#         servos["YAW"].set_target(50)
        servos["ROL"].set_target(70)
        servos["PIT"].set_target(70)
        servos["EAL"].set_target(100)
        servos["EYL"].set_target(60)
        servos["MOU"].set_target(20)
        servos["LID"].set_target(20)
        servos["EYR"].set_target(60)
        servos["EAL"].set_target(60)
        servos["EAR"].set_target(60)
    if animation_bool_a == True:
#         servos["YAW"].set_target(130)
        servos["ROL"].set_target(110)
        servos["PIT"].set_target(5)
        servos["EAL"].set_target(160)
        servos["EYL"].set_target(120)
        servos["MOU"].set_target(160)
        servos["LID"].set_target(160)
        servos["EYR"].set_target(120)
        servos["EAL"].set_target(120)
        servos["EAR"].set_target(120)
    if time.ticks_diff(now, last_toggle_a) >= 1000:
        animation_bool_a = not animation_bool_a   # flip the boolean
        last_toggle_a = now
        
# Note: system states:
#   - idle: sleeping, wakeword not initiated listening mode
#   - neutral: between finished speaking and begun listening. potentially use as marker for end of speech
#   - listening
#   - speaking
        
state_map={  
    "neutral": state_neutral,
    "idle": state_sleep,
    "listening": state_listen,
    "state_startup": state_startup,
    "thinking": state_thinking,
    "speaking": state_speaking,
    "state_limber_up": state_limber_up,
    "happy": state_happy,
    "sad": state_sad
}

#_________________#  #_________________#            


