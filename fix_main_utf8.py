import codecs

with codecs.open('main.py', 'r', 'utf-8') as f:
    lines = f.readlines()

with codecs.open('main.py', 'w', 'utf-8') as f:
    for line in lines:
        if 'conv_line = f"{conv_emoji}' in line:
            f.write('        conv_line = f"{conv_emoji} <b>Conviction:</b> <code>{conv_score:.0f}/100 ({conv_grade})</code> | Poz: %{conv_pos}\\n"\n')
        elif 'details_str = "<b>Puanlama' in line:
            f.write('        details_str = "<b>Puanlama DetaylarÄ±:</b>\\n"\n')
        elif 'details_str += f"' in line and 'k' in line and 'v' in line and '1f' in line:
            f.write('                details_str += f" â”œ {k}: <code>+{v:.1f}</code>\\n"\n')
        elif 'details_str +=' in line and 'â””' in line:
            f.write('        details_str += " â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\\n"\n')
        else:
            f.write(line)
print("Fixed successfully")
