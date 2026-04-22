import os
import ast
import yaml


def set_nested(d, key, value):
    parts = key.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


def get_nested(d, key):
    parts = key.split(".")
    for part in parts:
        if isinstance(d, dict) and part in d:
            d = d[part]
        else:
            return None
    return d


def deep_merge(d1, d2):
    """Merge dict d2 into d1 without overwriting existing non-dict values in d1."""
    for k, v in d2.items():
        if isinstance(v, dict):
            d1[k] = deep_merge(d1.get(k, {}), v)
        else:
            if k not in d1:
                d1[k] = v
    return d1


def main():
    texts = {}

    # 1. Extract texts from code
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

    # 2. Write messages.example.yaml
    with open("messages.example.yaml", "w", encoding="utf-8") as f:
        yaml.dump(texts, f, allow_unicode=True, default_flow_style=False, sort_keys=True)
    print("Updated messages.example.yaml")

    # 3. Update messages.yaml without overwriting existing keys
    messages_path = "messages.yaml"
    existing_texts = {}

    if os.path.exists(messages_path):
        with open(messages_path, "r", encoding="utf-8") as f:
            existing_texts = yaml.safe_load(f) or {}

    merged_texts = deep_merge(existing_texts, texts)

    with open(messages_path, "w", encoding="utf-8") as f:
        yaml.dump(merged_texts, f, allow_unicode=True, default_flow_style=False, sort_keys=True)
    print("Updated messages.yaml with new keys")


if __name__ == "__main__":
    main()
