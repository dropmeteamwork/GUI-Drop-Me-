import sys
import random
import string
import argparse

from gui import PROJECT_DIR

MACHINE_ID_LENGTH = 5


def generate_machine_id() -> str:
    """Generate a random machine ID consisting of uppercase letters and digits."""
    choice_strings = [string.ascii_uppercase, string.digits]
    return ''.join(
        random.choice(random.choice(choice_strings))
        for _ in range(MACHINE_ID_LENGTH))


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Generate a machine ID and save it to a file.")
    parser.add_argument("--output", type=str, help="Path to output file (default: machine_id.txt)")
    args = parser.parse_args(argv)
    
    machine_id = generate_machine_id()
    print(machine_id)

    with open(args.output, "w") as f:
        f.write(machine_id)


if __name__ == "__main__":
    main()
