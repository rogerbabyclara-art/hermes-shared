# form-helper-v2 — "C0XX 标红/失败" 排查路径

Use when user reports an account in the FormHelper UI showing red border / `failed` / `missing_*` / 任何 azure 注册警告. This is the **data-layer** trace path; do not start by patching code.

## Project layout (V3, current)
- Working dir: `D:\Projects\form-helper-v2`
- Account pool: `D:\Projects\form-helper-v2\proxies.json` (100 个号 `C001`-`C100`)
- CSV (form data source): `D:\Projects\form-helper-v2\accounts.csv` (445 行, serial 形如 `C020` 或 `1036`)
- Profile builder: `D:\Projects\form-helper-v2\azure\profile.js` (生成 warnings 数组)
- Account → CSV resolver: `D:\Projects\form-helper-v2\azure\index.js` `_resolveCsvSerialForName`

## proxies.json account schema (relevant fields)
```
name                    e.g. "C020"          # 身份锚点
linked_csv_serial       string (often "")    # 用户手动指派的 CSV serial (fallback only)
azure_status            idle|running|success|failed
azure_stage             start|browser_boot|...|browser_close
azure_last_msg          最后一次 stage 的消息或 warnings (例: "missing_address")
azure_finished_at       ms timestamp
azure_reason            人类可读原因
```

## resolveCsvSerialForName 优先级 (azure/index.js:77)
1. **CSV.serial === name** → 直配 (default, e.g. name=`C020` 匹配 CSV row serial=`C020`)
2. Fallback: `acc.linked_csv_serial` (用户手动指派时才有)
3. Error: 都没找到 → 报 "CSV 没有 serial=C0XX 的行"

**Note**: `linked_csv_serial` 通常是空字符串. 这不代表号没绑 CSV — 号靠 **name 同名直配** CSV.serial.

## profile.js warnings 字典 (azure/profile.js:91-98)
所有 `missing_*` 字符串都来自这里, 字段全是 **CSV 字段为空** 触发:

| warning | 触发条件 (CSV 字段全空才触发) |
|---|---|
| `missing_kanji_name`           | `firstNameJa` 或 `lastNameJa` 空 |
| `missing_romaji_name`          | `firstName` 或 `lastName` 空 **且** kanji_romaji 字典也没命中 |
| `missing_kana_name`            | romaji 推不出 kana (上游 romaji 空) |
| `missing_microsoft_credentials`| `email` 或 `password` 空 |
| `missing_backup_credentials`   | `backupEmail` 或 `backupPassword` 空 |
| `missing_address`              | `postalCode` / `prefecture` / `city` / `address` 任一空 |
| `missing_company`              | `company` 空 |

`isUsable = warnings.filter(w => w !== 'missing_company').length === 0` — `missing_company` 不阻断, 其它全阻断.

## 标准排查脚本 (Python, 跑在 hermes execute_code)

```python
import json, csv

acc_csv = r"D:\Projects\form-helper-v2\accounts.csv"
proxies_json = r"D:\Projects\form-helper-v2\proxies.json"

with open(acc_csv, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

data = json.load(open(proxies_json, encoding='utf-8'))
acc_by_name = {a['name']: a for a in data.get('accounts', [])}

# 改这里 — 要排查的号
TARGETS = ['C020', 'C023']

for name in TARGETS:
    a = acc_by_name.get(name)
    if not a:
        print(f"{name}: proxies.json 没这个号"); continue
    print(f"\n==== {name} ====")
    print(f"  azure_status:     {a.get('azure_status')}")
    print(f"  azure_stage:      {a.get('azure_stage')}")
    print(f"  azure_last_msg:   {a.get('azure_last_msg')}")
    print(f"  linked_csv_serial:{a.get('linked_csv_serial')!r}")

    # 优先 name 同名直配
    match = [r for r in rows if str(r['serial']) == name]
    src = 'name_match'
    if not match and a.get('linked_csv_serial'):
        match = [r for r in rows if str(r['serial']) == str(a['linked_csv_serial'])]
        src = 'linked_csv_serial'
    if not match:
        print(f"  !! CSV 找不到, 注册时会报错"); continue
    r = match[0]
    print(f"  CSV source:       {src}, serial={r['serial']}")
    for k in ['firstNameJa','lastNameJa','firstName','lastName',
              'postalCode','prefecture','city','address','address2',
              'email','password','backupEmail','backupPassword','company','done']:
        val = r.get(k, '')
        flag = '  ⚠ 空' if not val else ''
        print(f"    {k:20s} = {val!r}{flag}")
```

## 偏字/罗马音字典补全 (Pending User Asks #1)
- 字典文件: `D:\Projects\form-helper-v2\data\kanji_romaji_overrides.json` (或 kana.json 旁建新文件)
- 已知偏字: `徂徠 → Sorai` (C020), `気 → Ki` (C078)
- profile.js 第 62-66 行优先顺序: **字典命中 > 去音符的 CSV > 空**
- 修字典后, `missing_romaji_name` 和 `missing_kana_name` 同时消失 (kana 是 romaji 推出来的)

## 数据修复 vs 系统修复
- **数据修复** (5 分钟): 直接编辑 `accounts.csv` 把空字段补上 + reset proxies.json 的 azure_status/last_msg
- **系统修复**: 把字典文件补齐, 一次性解决所有同款偏字
- 推荐两个一起做: 字典补 + CSV 单点录入错(如 city/address 拆错)单独手补

## 常见陷阱
- 不要把 `linked_csv_serial==""` 当成 "号没绑 CSV" — 默认走 **name 同名直配**, 这字段只是手动指派的兜底.
- `azure_last_msg` 是**上次跑完留的旧消息**, 不会因为 CSV 数据修复自动消失. 修完数据要 reset `azure_status='idle'` + 清 `azure_last_msg` UI 红边框才消.
- 单 warning 是 `missing_romaji_name,missing_kana_name` 这种逗号串 — UI 截图常被截断显示成 `missing_romaji_name,missin...`, 不要被截断误导, 去 proxies.json 看完整串.
- `serial` 在 CSV 里既有 `C020` 形式也有纯数字 `1036` 形式, 字符串比较时 cast 成 `str()` 防止 int/str 不匹配.
