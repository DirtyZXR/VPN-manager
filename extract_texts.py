import os
import ast
import yaml


def set_nested(d, key, value):
    parts = key.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


texts = {}

for root, _, files in os.walk("app"):
    for file in files:
        if file.endswith(".py"):
            filepath = os.path.join(root, file)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name) and node.func.id == "t":
                            if len(node.args) >= 2:
                                if isinstance(node.args[0], ast.Constant) and isinstance(
                                    node.args[1], ast.Constant
                                ):
                                    key = node.args[0].value
                                    default = node.args[1].value
                                    set_nested(texts, key, default)
            except SyntaxError:
                pass

with open("messages.example.yaml", "w", encoding="utf-8") as f:
    yaml.dump(texts, f, allow_unicode=True, default_flow_style=False, sort_keys=True)

print("Extraction complete!")
