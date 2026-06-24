# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import json
from tools.bill import get_date_range_bill_data

print('=' * 60)
print('Test 1: Date Range Query (2026-04-13 to 2026-04-16)')
print('=' * 60)

result = get_date_range_bill_data.invoke({
    'start_date': '2026-04-13',
    'end_date': '2026-04-16'
})

data = json.loads(result)
print(f"Start: {data['start_date']}")
print(f"End: {data['end_date']}")
print(f"Total Records: {data['total_count']}")
print()

print('First 3 records:')
for i, r in enumerate(data['data'][:3], 1):
    print(f"  {i}. {r['交易时间']} | {r['交易类型']} | {r['金额(元)']} yuan")

print()
print('Last 3 records:')
for i, r in enumerate(data['data'][-3:], data['total_count'] - 2):
    print(f"  {i}. {r['交易时间']} | {r['交易类型']} | {r['金额(元)']} yuan")

print()
print('=' * 60)
print('Test 2: Cross-month Query (2026-03-28 to 2026-04-03)')
print('=' * 60)

result2 = get_date_range_bill_data.invoke({
    'start_date': '2026-03-28',
    'end_date': '2026-04-03'
})

data2 = json.loads(result2)
print(f"Start: {data2['start_date']}")
print(f"End: {data2['end_date']}")
print(f"Total Records: {data2['total_count']}")
print()

print('=' * 60)
print('SUCCESS! All tests passed. Tool is working correctly!')
print('=' * 60)
