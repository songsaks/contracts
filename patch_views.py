import re

def process_file():
    with open('pms/views.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    out_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out_lines.append(line)
        
        # Look for "if form.is_valid():" or something similar
        match = re.match(r'^(\s*)if (.+)\.is_valid\(\):', line)
        if match:
            indent = match.group(1)
            form_var_name = match.group(2)
            
            # Find the end of the if block
            j = i + 1
            is_end_of_block = False
            while j < len(lines):
                next_line = lines[j]
                if next_line.strip(): # non-empty line
                    next_indent_match = re.match(r'^(\s*)', next_line)
                    next_indent = next_indent_match.group(1) if next_indent_match else ''
                    
                    if len(next_indent) <= len(indent):
                        # Block has ended or next statement starts
                        if next_line.startswith(indent + 'else:'):
                            # Already has an else statement. Check if we need to add error msg.
                            pass
                        else:
                            # We should insert else block before this line
                            out_lines.extend(lines[i+1:j])
                            out_lines.append(indent + "else:\n")
                            out_lines.append(indent + "    messages.error(request, 'เกิดข้อผิดพลาดในการบันทึกข้อมูล กรุณาตรวจสอบความถูกต้อง')\n")
                            i = j - 1
                            is_end_of_block = True
                            break
                        
                j += 1
                
            if not is_end_of_block and j == len(lines):
                # end of file?
                pass
                
        i += 1
        
    with open('pms/views.py', 'w', encoding='utf-8') as f:
        f.writelines(out_lines)

process_file()
print("Done inserting else blocks.")
