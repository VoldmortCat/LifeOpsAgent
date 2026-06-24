# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tools.bill import get_date_range_bill_data

print('=' * 60)
print('Debug: Check return type')
print('=' * 60)

result = get_date_range_bill_data.invoke({
    'start_date': '2026-04-13',
    'end_date': '2026-04-16'
})

print(f'Result type: {type(result)}')
print(f'Result value: {result}')
print(f'Result repr: {repr(result)}')

if hasattr(result, 'content'):
    print(f'Content: {result.content}')
elif hasattr(result, 'text'):
    print(f'Text: {result.text}')

print()
print('Test completed!')
