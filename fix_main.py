import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Bozuk stringi bulalÄ±m
bad_block = '''        conv_emoji = {"STRONG": "ğŸŸ¢", "MEDIUM": "ğŸŸ¡", "WATCH": "ğŸŸ "}.get(conv_grade, "âšª")
                conv_line = f"{conv_emoji} <b>Conviction:</b> <code>{conv_score:.0f}/100 ({conv_grade})</code> | Poz: %{conv_pos}\\n"

    conv_details = trade_data.get('conviction_details')
    details_str = ""
    if conv_details and isinstance(conv_details, dict):
        details_str = "<b>Puanlama DetaylarÄ±:</b>\\n"
        for k, v in conv_details.items():
            if v > 0:
                details_str += f" â”œ {k}: <code>+{v:.1f}</code>\\n"
        details_str += " â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\\n"'''

good_block = '''        conv_emoji = {"STRONG": "ğŸŸ¢", "MEDIUM": "ğŸŸ¡", "WATCH": "ğŸŸ "}.get(conv_grade, "âšª")
        conv_line = f"{conv_emoji} <b>Conviction:</b> <code>{conv_score:.0f}/100 ({conv_grade})</code> | Poz: %{conv_pos}\\n"

    conv_details = trade_data.get('conviction_details')
    details_str = ""
    if conv_details and isinstance(conv_details, dict):
        details_str = "<b>Puanlama DetaylarÄ±:</b>\\n"
        for k, v in conv_details.items():
            if v > 0:
                details_str += f" â”œ {k}: <code>+{v:.1f}</code>\\n"
        details_str += " â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€\\n"'''

content = content.replace(bad_block, good_block)

# AyrÄ±ca, daha Ã¶nceki f"{details_str}" girmesi sÄ±rasÄ±nda hata olmuÅŸ olabilir. TÃ¼m dosyada aÅŸÄ±rÄ± girintileri dÃ¼zeltelim:
# '                conv_line =' => '        conv_line ='
content = content.replace('                conv_line = f', '        conv_line = f')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('main.py fixed.')
