import os

# Fix both template files - issue_description multiline problem
files = [
    r'd:\projects\contracts\templates\repairs\repair_detail.html',
    r'd:\projects\contracts\repairs\templates\repairs\repair_detail.html'
]

for filepath in files:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix the multiline issue_description variable tag
        # Replace the split version with a single-line version
        old_pattern = """<p class="text-gray-900 bg-gray-50 p-3 rounded-md border border-gray-200">{{
                            item.issue_description }}</p>"""
        new_pattern = """<p class="text-gray-900 bg-gray-50 p-3 rounded-md border border-gray-200">{{ item.issue_description }}</p>"""
        
        content = content.replace(old_pattern, new_pattern)
        
        # Write back
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Fixed issue_description in {filepath}")
    else:
        print(f"File not found: {filepath}")

print("All template files have been fixed for issue_description!")
