#!/usr/bin/env python3
import ast
import subprocess
from pathlib import Path

source_path = Path("app/hetzner_autoscaler.py")
source = source_path.read_text(encoding="utf-8")
tree = ast.parse(source)

cloud_fn = next(
    node for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "_cloud_init"
)
module = ast.Module(
    body=[
        ast.Assign(
            targets=[ast.Name(id="CONTROLLER_PUBLIC_URL", ctx=ast.Store())],
            value=ast.Constant(value="https://beonmeet.example.test"),
        ),
        cloud_fn,
    ],
    type_ignores=[],
)
ast.fix_missing_locations(module)
namespace = {}
exec(compile(module, str(source_path), "exec"), namespace)

cloud = namespace["_cloud_init"]("test-token")
assert cloud.startswith("#cloud-config\n"), cloud[:100]
assert "/internal/autoscale/status/test-token" in cloud
assert "/internal/autoscale/env/test-token" in cloud
assert "/internal/autoscale/profile/test-token" in cloud
assert "/internal/autoscale/images/test-token" in cloud
assert "--data-urlencode" in cloud
assert "package_update:" not in cloud
assert "packages:" not in cloud

marker = "runcmd:\n  - |\n"
assert marker in cloud
block = cloud.split(marker, 1)[1]
for line in block.splitlines():
    if line:
        assert line.startswith("      "), f"broken cloud-config indentation: {line!r}"

shell = "\n".join(
    line[6:] if line.startswith("      ") else line
    for line in block.splitlines()
)
subprocess.run(["bash", "-n"], input=shell, text=True, check=True)

assert '"detail=${2:-}"' in shell
assert "report cloud_init_started" in shell
assert "report prerequisites_ready" in shell
assert "report bootstrap_finished" in shell
assert "report bootstrap_failed" in shell

print("CLOUD_INIT_RENDER_TEST_PASS")
