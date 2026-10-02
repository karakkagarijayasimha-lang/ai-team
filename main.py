from info_mode import run_info_mode
from task_mode import run_task_mode


def main():
    while True:
        print("\n" + "=" * 60)
        print("                         AI TEAM")
        print("=" * 60)
        print("1. INFO MODE")
        print("2. TASK MODE")
        print("3. EXIT")
        print("=" * 60)

        choice = input("Choose a mode: ").strip()

        if choice == "1":
            try:
                run_info_mode()
            except KeyboardInterrupt:
                print("\nReturning to main menu...")
            except Exception as e:
                print(f"\nINFO MODE ERROR: {e}")

        elif choice == "2":
            try:
                run_task_mode()
            except KeyboardInterrupt:
                print("\nReturning to main menu...")
            except Exception as e:
                print(f"\nTASK MODE ERROR: {e}")

        elif choice == "3":
            print("\nAI TEAM closed.")
            break

        else:
            print("\nInvalid choice. Please enter 1, 2, or 3.")


if __name__ == "__main__":
    main()