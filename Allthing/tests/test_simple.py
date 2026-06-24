# -*- coding: utf-8 -*-
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from tools.bill import get_date_range_bill_data

print('Testing get_date_range_bill_data...')

result = get_date_range_bill_data.invoke({
    'start_date': '2026-04-13',
    'end_date': '2026-04-16'
})

print(f'Type: {type(result).__name__}')
print(f'Length: {len(result)} chars')
print()
print('First 800 chars of result:')
print(result[:800])
print()

if result.startswith('{'):
    import json
    data = json.loads(result)
    print(f'Parsed JSON - total_count: {data.get("total_count", "N/A")}')
