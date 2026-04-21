import os
import py_compile
import sys


def check_syntax(directory):
    errors = False
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                try:
                    py_compile.compile(filepath, doraise=True)
                except py_compile.PyCompileError as e:
                    print(f"Syntax error in {filepath}:\n{e}\n")
                    errors = True
                except Exception as e:
                    print(f"Error compiling {filepath}: {e}\n")
                    errors = True

    if not errors:
        print(f"All .py files in {directory} have valid syntax.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    check_syntax("app")
