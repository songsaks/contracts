"""เทียบไฟล์ JSON สองไฟล์ที่ได้จาก compare_scan_backends.py

รัน: python3 scratch/compare_scan_diff.py <ก่อน.json> <หลัง.json>
"""
import json, sys
old = json.load(open(sys.argv[1])); new = json.load(open(sys.argv[2]))
print(f"เดิม : {old['_backend']}")
print(f"ใหม่ : {new['_backend']}\n")
def flat(x, pre=''):
    o={}
    if isinstance(x, dict):
        for k,v in x.items(): o.update(flat(v, f'{pre}.{k}' if pre else str(k)))
    elif isinstance(x, list):
        for i,v in enumerate(x): o.update(flat(v, f'{pre}[{i}]'))
    else: o[pre]=x
    return o
TOL=1e-6; total=same=numd=typed=miss=0; diffs=[]; errs=[]
for kind in sorted(set(old['results'])|set(new['results'])):
    fo, fn = flat(old['results'].get(kind,{})), flat(new['results'].get(kind,{}))
    for k in sorted(set(fo)|set(fn)):
        total+=1; a,b = fo.get(k,'<ไม่มี>'), fn.get(k,'<ไม่มี>'); key=f'{kind}.{k}'
        if '__ERROR__' in k: errs.append((key,a,b)); continue
        if a=='<ไม่มี>' or b=='<ไม่มี>': miss+=1; diffs.append((key,a,b)); continue
        if isinstance(a,(int,float)) and isinstance(b,(int,float)) and not isinstance(a,bool) and not isinstance(b,bool):
            if abs(a-b)<=TOL: same+=1
            else: numd+=1; diffs.append((key,a,b))
        elif a==b: same+=1
        else: typed+=1; diffs.append((key,a,b))
print(f"เทียบ {total} ค่า  |  ตรงกัน {same}  ตัวเลขต่าง {numd}  ค่า/ชนิดต่าง {typed}  มีข้างเดียว {miss}")
if errs:
    print(f"\nฟังก์ชันที่ error ({len(errs)}):")
    for k,a,b in errs[:10]: print(f"  {k}\n     เดิม: {a}\n     ใหม่: {b}")
if diffs:
    print(f"\nต่างกัน {len(diffs)} จุด (แสดง 20 แรก):")
    for k,a,b in diffs[:20]: print(f"  {k}: {a}  ->  {b}")
else:
    print("\n>>> ไม่มีค่าไหนต่างกันเลย <<<")
