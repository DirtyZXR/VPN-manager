import compileall
import sys


def check_syntax(directory):
    success = compileall.compile_dir(directory, force=True)
    if success:
        print(f"All .py files in {directory} have valid syntax.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    check_syntax("app")
