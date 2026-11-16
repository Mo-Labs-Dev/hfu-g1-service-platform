# hfu_nav — autonomous walking tools

## Step A: Session 03 PCD -> 2D Nav2 map (read-only on Session 03)

Inside `g1pilot-dev`:

```bash
python3 /ros2_ws/src/g1pilot/hfu_nav/pcd_to_nav2_map.py \
    /ros2_ws/maps/hfu_lab_full/session_03/hfu_lab_static.pcd \
    --out /ros2_ws/maps/hfu_lab_full/nav2d_session03
```

Outputs: `map.pgm`, `map.yaml` (Nav2 map_server), `map_preview.png`, `map_info.json`.
Options: `--resolution 0.05`, `--min-height 0.10`, `--max-height 1.60`, `--no-level --floor-z Z`.
Tests: `python3 -m pytest -p no:anyio tests`

## Step B3: Offline localization test with the Session 03 bag

Inside `g1pilot-dev` (nothing moves; uses ROS_DOMAIN_ID=77 and localhost only):

```bash
bash /ros2_ws/src/g1pilot/hfu_nav/replay_session03.sh
```

Takes ~25 min at real time (`RATE=2.0` for faster, less reliable). Ctrl+C stops early and still writes
the result. Results: `/ros2_ws/maps/hfu_lab_full/localization_tests/replay_<time>/`
(`localization_summary.json`, `localization_route.png`, CSV log, launch/bag logs).

PASS rule: >= 95% of the route localized, no gap > 5 s, median RMSE <= 0.15 m.
