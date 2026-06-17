with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace actual literal newlines inside strings with \n (which happened because of powershell)
content = content.replace('Poz: %{conv_pos}\n"', 'Poz: %{conv_pos}\\n"')
content = content.replace('<b>Puanlama DetaylarÄ±:</b>\n"', '<b>Puanlama DetaylarÄ±:</b>\\n"')
content = content.replace('</code>\n"', '</code>\\n"')
content = content.replace('â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\n"', 'â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\\n"')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Done")
