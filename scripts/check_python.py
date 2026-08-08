import os
import py_compile
import sys

ADDONS_PATH = "custom_addons"
errors = []

if not os.path.isdir(ADDONS_PATH):
    print(f"❌ Directory not found: {ADDONS_PATH}")
    sys.exit(1)

for root, dirs, files in os.walk(ADDONS_PATH):
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)

            try:
                py_compile.compile(path, doraise=True)
                print(f"✓ {path}")
            except py_compile.PyCompileError as e:
                errors.append((path, str(e)))

if errors:
    print("\n❌ Python syntax errors found:")

    for path, error in errors:
        print(f"\n{path}")
        print(error)

    sys.exit(1)

print("\n✅ All Python files are valid.")
