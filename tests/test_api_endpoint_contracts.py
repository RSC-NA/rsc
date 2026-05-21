import ast
import importlib
from collections import defaultdict
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "rsc"


class EndpointCallCollector(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.import_aliases: dict[str, str] = {}
        self.local_api_vars: dict[str, str] = {}
        self.calls: list[tuple[str, str, Path, int]] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "rscapi":
            for alias in node.names:
                if alias.name.endswith("Api") and alias.name != "ApiClient":
                    self.import_aliases[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        api_class = self._api_class_from_call(node.value)
        if api_class:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.local_api_vars[target.id] = api_class
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        api_class = self._api_class_from_call(node.value)
        if api_class and isinstance(node.target, ast.Name):
            self.local_api_vars[node.target.id] = api_class
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            api_class = self.local_api_vars.get(node.func.value.id)
            if api_class:
                self.calls.append((api_class, node.func.attr, self.path, node.lineno))
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        previous = self.local_api_vars
        self.local_api_vars = {}
        self.generic_visit(node)
        self.local_api_vars = previous

    def _api_class_from_call(self, node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return self.import_aliases.get(node.func.id)
        return None


def _used_rscapi_endpoints() -> list[tuple[str, str, str]]:
    endpoints: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in SOURCE_ROOT.rglob("*.py"):
        collector = EndpointCallCollector(path)
        collector.visit(ast.parse(path.read_text(), filename=str(path)))
        for api_class, method_name, call_path, line_number in collector.calls:
            rel_path = call_path.relative_to(SOURCE_ROOT.parents[0])
            endpoints[(api_class, method_name)].add(f"{rel_path}:{line_number}")

    return [
        (api_class, method_name, ", ".join(sorted(locations)))
        for (api_class, method_name), locations in sorted(endpoints.items())
    ]


@pytest.mark.parametrize(("api_class_name", "method_name", "locations"), _used_rscapi_endpoints())
def test_used_rscapi_endpoint_method_exists(api_class_name: str, method_name: str, locations: str):
    api_class = getattr(importlib.import_module("rscapi"), api_class_name)

    assert hasattr(api_class, method_name), f"{api_class_name}.{method_name} is used at {locations} but is missing"
    assert callable(getattr(api_class, method_name)), f"{api_class_name}.{method_name} is used at {locations} but is not callable"
