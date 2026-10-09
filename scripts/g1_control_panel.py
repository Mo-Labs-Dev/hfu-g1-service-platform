from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

from robot.g1pilot_adapter.safety_controller import SafetyController


INTERFACE = "enP2p1s0"


def create_robot():
    print(f"Connecting using interface: {INTERFACE}")

    ChannelFactoryInitialize(0, INTERFACE)

    robot = LocoClient()
    robot.SetTimeout(10.0)
    robot.Init()

    print("Connected to G1.")

    return robot


def main():
    robot = create_robot()
    safety = SafetyController(robot)

    while True:
        print()
        print("================================")
        print("        G1 CONTROL PANEL")
        print("================================")
        print("1 - Read robot status")
        print("2 - Stop motion")
        print("3 - Damp robot")
        print("4 - Start robot [LOCKED]")
        print("5 - Move robot  [LOCKED]")
        print("Q - Quit")
        print()
        print("Physical E-stop is the primary")
        print("emergency safety control.")
        print("================================")

        choice = input("Select: ").strip().lower()

        try:
            if choice == "1":
                safety.print_state()

            elif choice == "2":
                safety.stop_motion()

            elif choice == "3":
                print()
                print("WARNING:")
                print("Damp changes the robot control state.")

                confirm = input(
                    "Type DAMP to confirm: "
                ).strip()

                safety.damp(
                    confirmed=(confirm == "DAMP")
                )

            elif choice == "4":
                safety.start_robot()

            elif choice == "5":
                safety.move(
                    vx=0.0,
                    vy=0.0,
                    yaw=0.0,
                )

            elif choice == "q":
                print("Closing G1 Control Panel.")
                break

            else:
                print("Unknown option.")

        except KeyboardInterrupt:
            print()
            print("Keyboard interrupt received.")
            print(
                "Use the physical E-stop if "
                "robot behavior is unexpected."
            )

        except Exception as exc:
            print()
            print(f"SAFETY: {exc}")


if __name__ == "__main__":
    main()
