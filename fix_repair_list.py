import os

# Fix repair_list.html multiline variables
files = [
    r'd:\projects\contracts\templates\repairs\repair_list.html',
    r'd:\projects\contracts\repairs\templates\repairs\repair_list.html'
]

for filepath in files:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix item.device.model multiline
        old = """<span class="truncate max-w-[150px]"
                                    title="{{ item.device.brand }} {{ item.device.model }}">{{ item.device.brand }} {{
                                    item.device.model }}</span>"""
        new = """<span class="truncate max-w-[150px]" title="{{ item.device.brand }} {{ item.device.model }}">{{ item.device.brand }} {{ item.device.model }}</span>"""
        
        content = content.replace(old, new)
        
        # Write back
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Fixed item.device.model in {filepath}")
    else:
        print(f"File not found: {filepath}")

print("repair_list.html multiline variables fixed!")
