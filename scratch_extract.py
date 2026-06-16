import ast
import json

appends = []

try:
    with open('c:/Users/YSR_MONSTER/.antigravity/Borsa/strategies.py', encoding='utf-8') as file:
        tree = ast.parse(file.read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and getattr(child.func, 'attr', '') == 'append' and getattr(child.func.value, 'id', '') == 'signals':
                    # Extract the dictionary
                    arg = child.args[0]
                    if isinstance(arg, ast.Dict):
                        d = {}
                        for key, value in zip(arg.keys, arg.values):
                            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                                d[key.value] = value.value
                        appends.append({
                            'function': node.name,
                            'strategy': d.get('strategy', 'Unknown'),
                            'signal': d.get('signal', 'Unknown')
                        })
except Exception as e:
    pass

with open('c:/Users/YSR_MONSTER/.antigravity/Borsa/scratch_output5.json', 'w', encoding='utf-8') as out:
    json.dump(appends, out, ensure_ascii=False, indent=2)

