import os

# Fix both template files - ALL remaining multiline variables
files = [
    r'd:\projects\contracts\templates\repairs\repair_detail.html',
    r'd:\projects\contracts\repairs\templates\repairs\repair_detail.html'
]

for filepath in files:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Fix customer_code
        old1 = """<dd class="mt-1 text-sm font-mono text-gray-600 bg-gray-100 inline-block px-2 rounded">{{
                            job.customer.customer_code }}</dd>"""
        new1 = """<dd class="mt-1 text-sm font-mono text-gray-600 bg-gray-100 inline-block px-2 rounded">{{ job.customer.customer_code }}</dd>"""
        content = content.replace(old1, new1)
        
        # Fix job_code
        old2 = """<dd class="mt-1 text-sm font-mono text-gray-600 bg-gray-100 inline-block px-2 rounded">{{
                            job.job_code }}</dd>"""
        new2 = """<dd class="mt-1 text-sm font-mono text-gray-600 bg-gray-100 inline-block px-2 rounded">{{ job.job_code }}</dd>"""
        content = content.replace(old2, new2)
        
        # Write back
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Fixed customer_code and job_code in {filepath}")
    else:
        print(f"File not found: {filepath}")

print("All remaining multiline variables fixed!")
