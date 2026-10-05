from modules.navigation.models import NavigationGoal
from modules.navigation.navigation_module import NavigationModule
from robot.g1pilot_adapter.navigation_adapter import G1PilotNavigationAdapter


adapter = G1PilotNavigationAdapter()
navigation = NavigationModule(adapter)

navigation.initialize()

goal = NavigationGoal(
    name="3d_printer",
    x=4.2,
    y=1.8,
    yaw=0.0
)

navigation.go_to(goal)

print("Status:", navigation.get_status().value)
