import pytest

from robot.teleop.motion_backends import MockMotionBackend
from robot.teleop.teleop_controller import (
    InvalidToken,
    LeaseBusy,
    PinLockedOut,
    PinRejected,
    TeleopController,
    TeleopLimits,
)


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def make(fsm=500, **limit_overrides):
    clock = FakeClock()
    backend = MockMotionBackend(fsm_id=fsm)
    limits = TeleopLimits(**limit_overrides)
    ctrl = TeleopController(backend, pin="4821", limits=limits, clock=clock)
    return ctrl, backend, clock


def drive(ctrl, clock, token, x=0.0, y=0.0, yaw=0.0, ticks=1, dt=0.05):
    for _ in range(ticks):
        ctrl.command(token, x, y, yaw)
        clock.advance(dt)
        ctrl.step()


# --- authentication / lease -------------------------------------------

def test_no_motion_without_unlock():
    ctrl, backend, clock = make()
    with pytest.raises(InvalidToken):
        ctrl.command("bogus", 1.0, 0, 0)
    ctrl.step()
    assert backend.commands == []
    assert ctrl.status()["state"] == "locked"


def test_wrong_pin_rejected_and_lockout():
    ctrl, _, clock = make(max_pin_failures=3, pin_lockout_seconds=60)
    for _ in range(3):
        with pytest.raises(PinRejected):
            ctrl.unlock("0000")
    with pytest.raises(PinLockedOut):
        ctrl.unlock("4821")
    clock.advance(61)
    assert ctrl.unlock("4821")


def test_unconfigured_pin_refuses_everyone():
    ctrl = TeleopController(MockMotionBackend(), pin="")
    with pytest.raises(PinRejected):
        ctrl.unlock("")


def test_single_operator_lease():
    ctrl, _, _ = make()
    ctrl.unlock("4821", "alice")
    with pytest.raises(LeaseBusy):
        ctrl.unlock("4821", "bob")


def test_lease_expires_when_idle():
    ctrl, _, clock = make(lease_idle_timeout=30)
    token = ctrl.unlock("4821")
    clock.advance(31)
    assert not ctrl.is_token_valid(token)
    assert ctrl.unlock("4821")  # someone else may take over


def test_lock_stops_robot():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    ctrl.step()  # FSM read
    drive(ctrl, clock, token, x=1.0, ticks=5)
    ctrl.lock(token)
    assert backend.stop_count >= 1
    with pytest.raises(InvalidToken):
        ctrl.command(token, 1, 0, 0)


# --- motion ----------------------------------------------------------

def test_forward_ramps_up_and_respects_limit():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=40)
    speeds = [c[0] for c in backend.commands]
    assert speeds[0] < speeds[-1]                     # ramped, not jumped
    assert max(speeds) == pytest.approx(0.30)         # clamped
    assert all(c[3] == pytest.approx(0.40) for c in backend.commands)


def test_backward_slower_than_forward():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=-1.0, ticks=40)
    assert min(c[0] for c in backend.commands) == pytest.approx(-0.15)


def test_out_of_range_input_is_clamped():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, yaw=50.0, ticks=40)
    assert max(c[2] for c in backend.commands) == pytest.approx(0.40)


def test_deadband_ignores_small_stick_noise():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=0.05, y=-0.05, ticks=10)
    assert backend.commands == []


def test_nan_command_rejected_and_stops():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    with pytest.raises(ValueError):
        ctrl.command(token, float("nan"), 0, 0)
    assert backend.stop_count == 1


def test_speed_scale():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    for _ in range(40):
        ctrl.command(token, 1.0, 0, 0, speed_scale=0.5)
        clock.advance(0.05)
        ctrl.step()
    assert max(c[0] for c in backend.commands) == pytest.approx(0.15)


# --- safety ----------------------------------------------------------

def test_deadman_stops_when_messages_stop():
    ctrl, backend, clock = make(command_timeout=0.3)
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=20)
    sent = len(backend.commands)
    # App freezes / Wi-Fi drops: no more commands.
    clock.advance(0.35)
    ctrl.step()
    assert backend.stop_count == 1
    assert len(backend.commands) == sent
    assert ctrl.status()["state"] == "idle"


def test_release_stick_decelerates_then_stops():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=40)
    n = len(backend.commands)
    drive(ctrl, clock, token, x=0.0, ticks=20)
    tail = [c[0] for c in backend.commands[n:]]
    assert tail == sorted(tail, reverse=True)  # monotonic slow-down
    assert backend.stop_count == 1


def test_wrong_fsm_blocks_motion():
    ctrl, backend, clock = make(fsm=4)  # StandUp, not locomotion
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=10)
    assert backend.commands == []
    assert ctrl.status()["state"] == "not_locomotion_ready"


def test_fsm_change_during_motion_stops_robot():
    ctrl, backend, clock = make(fsm_check_period=0.2)
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=10)
    backend.fsm_id = 1  # robot fell into damp
    drive(ctrl, clock, token, x=1.0, ticks=10)
    assert backend.stop_count == 1
    assert ctrl.status()["output"] == {"vx": 0.0, "vy": 0.0, "yaw": 0.0}


def test_unreadable_fsm_blocks_motion():
    ctrl, backend, clock = make(fsm=None)
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=5)
    assert backend.commands == []


def test_estop_latches_until_reset():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=10)
    ctrl.estop()
    n = len(backend.commands)
    drive(ctrl, clock, token, x=1.0, ticks=10)
    assert len(backend.commands) == n           # ignored while latched
    assert ctrl.status()["estop"] is True
    ctrl.reset_estop(token)
    drive(ctrl, clock, token, x=1.0, ticks=5)
    assert len(backend.commands) > n


def test_estop_reset_requires_token():
    ctrl, _, _ = make()
    ctrl.unlock("4821")
    ctrl.estop()
    with pytest.raises(InvalidToken):
        ctrl.reset_estop("bogus")


def test_backend_error_latches_estop():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=3)
    backend.fail_next = True
    drive(ctrl, clock, token, x=1.0, ticks=1)
    st = ctrl.status()
    assert st["estop"] and st["estop_reason"] == "backend_error"
    assert backend.stop_count >= 1


def test_stop_needs_no_token():
    ctrl, backend, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=5)
    ctrl.stop()
    assert backend.stop_count == 1
    assert ctrl.status()["output"]["vx"] == 0.0


# --- robot modes -----------------------------------------------------

from robot.teleop.teleop_controller import ModeRejected  # noqa: E402


def test_status_ready_when_stick_centered():
    ctrl, _, clock = make()
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=0.0, ticks=3)
    assert ctrl.status()["state"] == "ready"


def test_mode_sequence_damp_stand_walk():
    ctrl, backend, clock = make(fsm=1)
    token = ctrl.unlock("4821")
    assert ctrl.request_mode(token, "stand_up") == 4
    clock.advance(3)
    assert ctrl.request_mode(token, "walk") == 500
    assert backend.fsm_requests == [4, 500]
    assert ctrl.status()["fsm_id"] == 500


def test_walk_rejected_from_damp():
    ctrl, backend, _ = make(fsm=1)
    token = ctrl.unlock("4821")
    with pytest.raises(ModeRejected):
        ctrl.request_mode(token, "walk")
    assert backend.fsm_requests == []


def test_stand_rejected_while_walking():
    ctrl, backend, _ = make(fsm=500)
    token = ctrl.unlock("4821")
    with pytest.raises(ModeRejected):
        ctrl.request_mode(token, "stand_up")
    assert backend.fsm_requests == []


def test_damp_always_allowed_even_in_estop_and_unknown_fsm():
    ctrl, backend, _ = make(fsm=None)
    token = ctrl.unlock("4821")
    ctrl.estop()
    assert ctrl.request_mode(token, "damp") == 1
    assert backend.fsm_requests == [1]


def test_mode_change_stops_motion_first():
    ctrl, backend, clock = make(fsm=500)
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=10)
    stops = backend.stop_count
    ctrl.request_mode(token, "damp")
    assert backend.stop_count == stops + 1
    assert ctrl.status()["output"]["vx"] == 0.0


def test_mode_requires_token_and_cooldown():
    ctrl, _, clock = make(fsm=1)
    with pytest.raises(InvalidToken):
        ctrl.request_mode("bogus", "damp")
    token = ctrl.unlock("4821")
    ctrl.request_mode(token, "stand_up")
    with pytest.raises(ModeRejected):
        ctrl.request_mode(token, "damp")  # too fast
    clock.advance(2.5)
    ctrl.request_mode(token, "damp")


def test_stand_and_walk_blocked_during_estop():
    ctrl, _, _ = make(fsm=1)
    token = ctrl.unlock("4821")
    ctrl.estop()
    with pytest.raises(ModeRejected):
        ctrl.request_mode(token, "stand_up")


def test_unknown_mode_and_zero_torque_not_offered():
    ctrl, _, _ = make()
    token = ctrl.unlock("4821")
    for bad in ("zero_torque", "0", ""):
        with pytest.raises(ModeRejected):
            ctrl.request_mode(token, bad)


# --- gestures --------------------------------------------------------

def make_gesture_ctrl(fsm=500):
    ctrl, backend, clock = make(
        fsm=fsm, gesture_hold_seconds=0.0, handshake_hold_seconds=0.0
    )
    ctrl._spawn = lambda fn: fn()  # run inline
    token = ctrl.unlock("4821")
    ctrl.step()  # read FSM
    return ctrl, backend, clock, token


def test_gesture_runs_and_reports_done():
    ctrl, backend, _, token = make_gesture_ctrl()
    ctrl.perform_gesture(token, "high_wave")
    assert backend.arm_actions == [26]
    st = ctrl.status()
    assert st["gesture"] is None and "done" in st["gesture_result"]


def test_sustained_gesture_releases_arms():
    ctrl, backend, _, token = make_gesture_ctrl()
    ctrl.perform_gesture(token, "heart")
    assert backend.arm_actions == [20, 99]


def test_gesture_needs_walking_mode():
    ctrl, backend, _, token = make_gesture_ctrl(fsm=4)
    with pytest.raises(ModeRejected):
        ctrl.perform_gesture(token, "clap")
    assert backend.arm_actions == []


def test_gesture_blocked_in_estop_and_without_token():
    ctrl, backend, _, token = make_gesture_ctrl()
    with pytest.raises(InvalidToken):
        ctrl.perform_gesture("bogus", "clap")
    ctrl.estop()
    with pytest.raises(ModeRejected):
        ctrl.perform_gesture(token, "clap")
    assert backend.arm_actions == []


def test_unknown_gesture_rejected():
    ctrl, _, _, token = make_gesture_ctrl()
    with pytest.raises(ModeRejected):
        ctrl.perform_gesture(token, "backflip")


def test_gesture_stops_walking_and_blocks_joystick():
    ctrl, backend, clock = make(fsm=500, gesture_hold_seconds=0.0)
    pending = []
    ctrl._spawn = pending.append  # hold the gesture "running"
    token = ctrl.unlock("4821")
    drive(ctrl, clock, token, x=1.0, ticks=10)
    ctrl.perform_gesture(token, "clap")
    n = len(backend.commands)
    drive(ctrl, clock, token, x=1.0, ticks=5)
    assert len(backend.commands) == n          # joystick ignored
    assert ctrl.status()["state"] == "gesture"
    with pytest.raises(ModeRejected):
        ctrl.perform_gesture(token, "clap")      # one at a time
    pending[0]()                                 # gesture finishes
    drive(ctrl, clock, token, x=1.0, ticks=5)
    assert len(backend.commands) > n             # driving again


def test_arm_raised_error_releases_and_reports():
    ctrl, backend, _, token = make_gesture_ctrl()
    backend.arm_codes = [7401]
    ctrl.perform_gesture(token, "clap")
    assert backend.arm_actions == [17, 99]
    assert "lowered" in ctrl.status()["gesture_result"]


def test_firmware_error_reported():
    ctrl, backend, _, token = make_gesture_ctrl()
    backend.arm_codes = [7404]
    ctrl.perform_gesture(token, "hug")
    assert "not allowed" in ctrl.status()["gesture_result"]
    assert ctrl.status()["gesture"] is None


# --- visitor demo mode -----------------------------------------------

def make_demo(fsm=500):
    ctrl, backend, clock, token = make_gesture_ctrl(fsm=fsm)
    ctrl.set_demo_mode(token, True)
    return ctrl, backend, clock, token


def test_robot_show_works_automatically_without_pin():
    ctrl, backend, clock = make(fsm=500, gesture_hold_seconds=0.0)
    ctrl._spawn = lambda fn: fn()
    ctrl.step()  # read FSM; nobody unlocked anything
    assert ctrl.demo_status()["available"] is True
    ctrl.visitor_gesture("high_wave")
    assert backend.arm_actions == [26]


def test_robot_show_can_be_disabled_on_server():
    ctrl, backend, _ = make(fsm=500, robot_show_enabled=False)
    ctrl.step()
    assert ctrl.demo_status()["reason"] == "off"
    with pytest.raises(ModeRejected):
        ctrl.visitor_gesture("high_wave")


def test_visitor_cannot_use_contact_gestures():
    ctrl, backend, _, _ = make_demo()
    for g in ("hug", "shake_hand", "high_five", "release_arm", "x"):
        with pytest.raises(ModeRejected):
            ctrl.visitor_gesture(g)
    assert backend.arm_actions == []


def test_visitor_cooldown():
    ctrl, backend, clock, _ = make_demo()
    ctrl.visitor_gesture("clap")
    assert ctrl.demo_status()["reason"] == "resting"
    with pytest.raises(ModeRejected):
        ctrl.visitor_gesture("clap")
    clock.advance(4.5)
    ctrl.visitor_gesture("clap")
    assert backend.arm_actions == [17, 17]


def test_visitor_blocked_while_robot_moves():
    ctrl, backend, clock, token = make_demo()
    drive(ctrl, clock, token, x=1.0, ticks=5)
    assert ctrl.demo_status()["reason"] == "moving"
    with pytest.raises(ModeRejected):
        ctrl.visitor_gesture("clap")


def test_visitor_blocked_in_estop_and_wrong_fsm():
    ctrl, _, _, _ = make_demo()
    ctrl.estop()
    assert ctrl.demo_status()["reason"] == "stopped"
    with pytest.raises(ModeRejected):
        ctrl.visitor_gesture("clap")
    ctrl2, _, _, _ = make_demo(fsm=4)
    assert ctrl2.demo_status()["reason"] == "not_ready"
    with pytest.raises(ModeRejected):
        ctrl2.visitor_gesture("clap")


def test_robot_show_blocked_after_damp_until_walking_again():
    ctrl, backend, clock, token = make_demo()
    ctrl.request_mode(token, "damp")
    ctrl.lock(token)
    clock.advance(5)
    ctrl.step()
    assert ctrl.demo_status()["reason"] == "not_ready"
    with pytest.raises(ModeRejected):
        ctrl.visitor_gesture("heart")
    assert backend.arm_actions == []


def test_demo_mode_requires_operator_token():
    ctrl, _, _, _ = make_gesture_ctrl()
    with pytest.raises(InvalidToken):
        ctrl.set_demo_mode("bogus", True)


# --- voice gestures --------------------------------------------------

def test_voice_allows_handshake_and_high_five_but_not_hug():
    ctrl, backend, clock, _ = make_demo()
    ctrl.visitor_gesture("shake_hand", by_voice=True)
    assert backend.arm_actions == [27, 99]        # hand out, then arms down
    clock.advance(5)
    ctrl.visitor_gesture("high_five", by_voice=True)
    assert backend.arm_actions[-2:] == [18, 99]
    clock.advance(5)
    with pytest.raises(ModeRejected):
        ctrl.visitor_gesture("hug", by_voice=True)


def test_touch_screen_still_cannot_handshake():
    ctrl, backend, _, _ = make_demo()
    with pytest.raises(ModeRejected):
        ctrl.visitor_gesture("shake_hand")
    assert backend.arm_actions == []


def test_voice_gesture_same_safety_rules():
    ctrl, backend, clock, token = make_demo()
    drive(ctrl, clock, token, x=1.0, ticks=5)
    with pytest.raises(ModeRejected):
        ctrl.visitor_gesture("shake_hand", by_voice=True)   # moving
    ctrl2, b2, _, _ = make_demo(fsm=4)
    with pytest.raises(ModeRejected):
        ctrl2.visitor_gesture("shake_hand", by_voice=True)  # not walking mode
    assert backend.arm_actions == [] and b2.arm_actions == []


def test_stop_count_increments_on_stop_and_estop():
    ctrl, _, _ = make()
    assert ctrl.status()["stop_count"] == 0
    ctrl.stop()
    ctrl.estop()
    assert ctrl.status()["stop_count"] == 2
