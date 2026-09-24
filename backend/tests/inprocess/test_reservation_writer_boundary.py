"""New route writers must not bypass the transactional reservation store."""
import ast
from pathlib import Path


def test_production_reservation_writers_use_the_store():
    root = Path(__file__).resolve().parents[2]
    violations = []
    mutations = {'insert_one', 'insert_many', 'update_one', 'update_many',
                 'delete_one', 'delete_many', 'find_one_and_update', 'replace_one'}
    for folder in ('routes', 'services', 'seeds'):
        for path in (root / folder).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in mutations:
                    continue
                owner = node.func.value
                if (isinstance(owner, ast.Attribute) and owner.attr == 'reservations'
                        and isinstance(owner.value, ast.Name) and owner.value.id == 'db'):
                    violations.append(f'{path.relative_to(root)}:{node.lineno}')
    assert not violations, violations
