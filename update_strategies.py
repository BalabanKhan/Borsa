import re

with open('strategies.py', 'r', encoding='utf-8') as f:
    content = f.read()

def repl(m):
    return m.group(1) + ' \"conviction_details\": ' + m.group(2) + '.component_scores,'

new_content = re.sub(r"([\"'']conviction_grade[\"'']:\s*([A-Za-z0-9_]+)\.grade,?)", repl, content)

with open('strategies.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Updated strategies.py')
