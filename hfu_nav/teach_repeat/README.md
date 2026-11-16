# Teach & repeat guiding (G1)

Visitor: "G1, guide me to the coffee machine" → G1 walks the taught route,
stops for obstacles, announces arrival, waits, walks back home.

## Pieces

| File | What |
|---|---|
| `start_fastlio_live.sh` | live FAST-LIO, mapping-day settings, **no map saving** |
| `route_tool.py odom` | live check: does FAST-LIO measure walking correctly? |
| `route_tool.py record NAME` | teach a route while driving with the app joystick |
| `route_tool.py list / check NAME` | list routes / am I on the home spot? |
| `guide_service.py` | runs the guide, HTTP API on port **8002** |
| `routes/*.json` | taught routes (folder `hfu_nav/routes`) |

Motion goes through the teleop server (8001): speed limits, dead-man,
FSM 500, E-stop apply. App STOP / E-STOP cancels a guide.

## Safety behaviour of the guide
- refuses to start: no FSM 500, E-stop, joystick in use, gesture running,
  no live odometry, not on the home spot (>0.6 m / >25°)
- stops & waits if something is 0.2–1.2 m in front (0.25–1.6 m high);
  asks "please let me pass" after 6 s; gives up after 90 s
- aborts: odometry stale >2 s, odometry jump >0.4 m, height drift >0.5 m
  (FAST-LIO runaway), >0.8 m off the taught route, robot leaves FSM 500
- LiDAR blind zone: FAST-LIO `blind: 1.0` hides points closer than 1 m to
  the head LiDAR → low obstacles (legs) are seen, objects at head height
  only from ~1 m. Always supervise with the remote in hand.

## Procedure
1. Mark HOME on the floor (tape for both feet + a heading line).
2. G1 on HOME, walking mode (FSM 500). Livox driver running.
3. `bash start_fastlio_live.sh`  (new origin = home)
4. `python3 route_tool.py odom` → walk 5 m forward with the joystick → ~5 m?
5. Back to HOME. Restart FAST-LIO (step 3) so home = origin again.
6. `python3 route_tool.py record coffee_machine --title-en "coffee machine" --title-de "Kaffeemaschine"`
   → drive to the destination slowly, stop, Ctrl+C.
7. Drive back to HOME, restart FAST-LIO, then start the guide service and try it.
   Restart FAST-LIO on HOME before each guiding session.
