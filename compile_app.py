import compileall
import sys
import io
from contextlib import redirect_stdout


def main():
    print("Compiling app/ directory...")

    # Capture the output of compileall
    f = io.StringIO()
    with redirect_stdout(f):
        success = compileall.compile_dir("app/", force=True)

    output = f.getvalue()
    print(output)

    if success:
        print("Compilation successful.")
        sys.exit(0)
    else:
        print("Compilation failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
