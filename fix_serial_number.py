import os

# Fix both template files - serial_number multiline problem
files = [
    r'd:\projects\contracts\templates\repairs\repair_detail.html',
    r'd:\projects\contracts\repairs\templates\repairs\repair_detail.html'
]

for filepath in files:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix the multiline serial_number variable tag
        old_pattern = """<span class="ml-2 text-sm font-normal text-gray-500">({{ item.device.serial_number|default:"No
                            Serial" }})</span>"""
        new_pattern = """<span class="ml-2 text-sm font-normal text-gray-500">({{ item.device.serial_number|default:"No Serial" }})</span>"""
        
        content = content.replace(old_pattern, new_pattern)
        
        # Write back
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Fixed serial_number in {filepath}")
    else:
        print(f"File not found: {filepath}")

print("All template files have been fixed for serial_number!")
