import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Ekleme 1: conv_line altına details_str
insert_details = '''        conv_line = f\"{conv_emoji} <b>Conviction:</b> <code>{conv_score:.0f}/100 ({conv_grade})</code> | Poz: %{conv_pos}\\n\"

    conv_details = trade_data.get('conviction_details')
    details_str = \"\"
    if conv_details and isinstance(conv_details, dict):
        details_str = \"<b>Puanlama Detayları:</b>\\n\"
        for k, v in conv_details.items():
            if v > 0:
                details_str += f\" ├ {k}: <code>+{v:.1f}</code>\\n\"
        details_str += \" └────────────────\\n\"'''

content = re.sub(
    r'conv_line = f\"\{conv_emoji\} <b>Conviction:</b> <code>\{conv_score:\.0f\}/100 \(\{conv_grade\}\)</code> \| Poz: %\{conv_pos\}\\n\"',
    insert_details,
    content
)

# Ekleme 2: msg stringi içine details_str yerleştir
insert_msg = '''        f\"{rr_line}\"
        f\"{conv_line}\"
        f\"{details_str}\"
        f\"-------------------------------------\\n\"'''

content = re.sub(
    r'f\"\{rr_line\}\"\s+f\"\{conv_line\}\"\s+f\"-------------------------------------\\n\"',
    insert_msg,
    content
)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Updated main.py')
