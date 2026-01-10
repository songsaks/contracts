import os

# Fix both template files
files = [
    r'd:\projects\contracts\templates\repairs\repair_detail.html',
    r'd:\projects\contracts\repairs\templates\repairs\repair_detail.html'
]

for filepath in files:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix all instances of status== to status ==
        content = content.replace("item.status=='RECEIVED'", "item.status == 'RECEIVED'")
        content = content.replace("item.status=='FIXING'", "item.status == 'FIXING'")
        content = content.replace("item.status=='WAITING'", "item.status == 'WAITING'")
        content = content.replace("item.status=='FINISHED'", "item.status == 'FINISHED'")
        
        # Write back
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Fixed {filepath}")
    else:
        print(f"File not found: {filepath}")

print("All template files have been fixed!")
