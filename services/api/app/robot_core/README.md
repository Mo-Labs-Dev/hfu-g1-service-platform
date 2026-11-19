Copies of the robot guide code (g1pilot-main/hfu_nav/teach_repeat) used by the
G1 Studio simulator, so the simulation runs EXACTLY the same follower / tour logic
as the real robot. Update these copies when the robot code changes:

    cp ~/Documents/Projekte/g1pilot-main/hfu_nav/teach_repeat/{route_core,guide_runner,home_align}.py \
       ~/Documents/Projekte/hfu-g1-studio/services/api/app/robot_core/
