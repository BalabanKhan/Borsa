import re

with open('main.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix newline dangling quote
text = text.replace('        details_str = "<b>Puanlama DetaylarÄ±:</b>\\n"\n"\n', '        details_str = "<b>Puanlama Detayları:</b>\\n"\n')
text = text.replace('        details_str += " └────────────────\n"\n', '        details_str += " └────────────────\\n"\n')
text = text.replace('        details_str = "<b>Puanlama Detayları:</b>\\n"\n"\n', '        details_str = "<b>Puanlama Detayları:</b>\\n"\n')
text = text.replace('        details_str += " └────────────────\\n"\n"\n', '        details_str += " └────────────────\\n"\n')

# General cleanup for any dangling double quote on a newline
text = re.sub(r'\\n"\n"\n', r'\\n"\n', text)
text = re.sub(r'\n"\n\s+for k, v', r'\n        for k, v', text)
text = re.sub(r'└────────────────\n"', r'└────────────────\\n"', text)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(text)
