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
- stops & waits if something is ON THE TAUGHT PATH 0.2–1.2 m ahead (±0.30 m corridor that bends with the route, plus ±0.15 m straight in front; 0.25–1.6 m high) - walls and door frames beside the route are ignored;
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

## Lab tour (several stops, G1 explains each one)
A tour is one taught route with **stops** marked while teaching.
1. G1 on HOME, FAST-LIO restarted on HOME (as above).
2. `python3 route_tool.py record lab_tour --tour --title-en "HFU lab tour" --title-de "HFU Laborführung"`
3. Drive slowly through the lab. At each exhibit: stop, **turn G1 to face the
   exhibit**, type a short name (e.g. `3d_printer`) in the terminal, press Enter.
4. Finish back on HOME, facing the start direction, then Ctrl+C.
   (Tour ends on HOME = loop → G1 needs no extra way back.)
5. `python3 route_tool.py stops lab_tour` → see the stops
6. `python3 route_tool.py stop-text lab_tour 1 --title-en "3D printer" --title-de "3D-Drucker" --text-en "..." --text-de "..."`
   (empty text → "Here you can see the <title>.")

When guiding a tour G1: welcomes → walks to stop 1 → turns to the exhibit →
explains → "Let's continue" → … → back on HOME → "Thank you for visiting".
Same safety rules as a normal guide. Visitor says "give me a lab tour" /
"zeig mir das Labor" in Talk to G1, or `POST /api/guide/start {"route": "lab_tour"}`.
Keep tours to ~4–6 stops and under ~60 m; check the drift at the end like for routes.

## Automatic HOME alignment (18 Nov)
Routes are stored in the FAST-LIO frame of the teaching run (origin = where G1
stood). A few degrees of placement error rotate the whole route (5° ≈ 0.9 m at
10 m). Now:
- `record` keeps G1 still for 3 s at the start and saves `routes/NAME.home.npz`
  (2D wall slice 0.3–2.2 m high, 5 cm voxels).
- Before every guide/tour the guide collects 2.5 s of scans at HOME, matches them
  to the saved scan (2D ICP, numpy only) and converts poses + points into the
  teaching frame. Result is in `GET /api/guide/status` → `alignment`
  (dx, dy, dyaw_deg, fit) – log it for the thesis.
- Refuses to start if the match is poor (< 45 %), > 1 m or > 20° off.
- Routes recorded before 18 Nov have no HOME scan → run unchanged (re-record them).
