"""安全计算器工具 —— 仅 LLM 调用的通用四则运算工具。

LLM 不参与任何计算过程，只负责将自然语言翻译为标准表达式。
所有计算由 Python eval() 在严格沙箱中执行。
"""

import re
import logging
from typing import Tuple
from langchain_core.tools import tool

logger = logging.getLogger("lifeops.calculator")

# 安全白名单：仅允许数字、四则运算符、括号、小数点、空格
SAFE_CHARACTERS = re.compile(r'^[0-9+\-*/(). ]+$')

# 表达式清理：去掉所有空白后检查
CLEAN_RE = re.compile(r'\s+')


def validate_expression(expression: str) -> Tuple[bool, str]:
    """对表达式进行多层安全校验。

    Args:
        expression: LLM 生成的表达式字符串

    Returns:
        (是否合法, 错误信息) — 合法时 error 为空字符串
    """
    original = expression

    # 1. 字符白名单校验
    if not SAFE_CHARACTERS.match(expression):
        # 找出非法字符
        illegal = set(expression) - set('0123456789+-*/(). ')
        return False, f"表达式包含非法字符: {''.join(illegal)}。仅允许数字、+、-、*、/、(、)和空格"

    # 2. 移除空格后检查空表达式
    cleaned = CLEAN_RE.sub('', expression)
    if not cleaned:
        return False, "表达式不能为空"
    expression = cleaned

    # 3. 括号匹配校验
    stack = []
    for i, char in enumerate(expression):
        if char == '(':
            stack.append(i)
        elif char == ')':
            if not stack:
                return False, f"位置{i}的右括号没有匹配的左括号"
            stack.pop()
    if stack:
        return False, f"位置{stack[0]}的左括号没有匹配的右括号"

    # 4. 不能以运算符开头（负号除外）
    if expression[0] in '+*/':
        return False, f"表达式不能以'{expression[0]}'开头（负号可以使用-）"

    # 5. 不能以运算符结尾
    if expression[-1] in '+-*/':
        return False, f"表达式不能以运算符结尾"

    # 6. 连续运算符校验（--可以，是负负得正）
    if re.search(r'[+*/]{2,}', expression):
        return False, "存在连续运算符"
    if re.search(r'-\*|-\+|-/', expression):
        return False, f"运算符组合不合法"

    # 7. 纯表达式结构校验：括号和运算符之间必须有数字
    if re.search(r'\([+\-*/]', expression):
        return False, "左括号后不能直接跟运算符"

    if re.search(r'[+\-*/]\)', expression):
        return False, "右括号前不能是运算符"

    return True, ""


@tool
def calculate(expression: str) -> str:
    """执行安全的四则运算。

    你可以将自然语言计算需求转换为标准数学表达式后调用本工具。
    表达式仅支持: 数字(含小数)、+、-、*、/、(、)

    ⚠️ 重要规则：
    1. 你绝对不能自己计算结果，必须调用本工具！
    2. 工具返回的结果必须原样使用，不得修改任何数字！
    3. 表达式中的数字必须来自真实数据（ToolMessage或用户输入），不得编造！

    使用示例：
      - calculate("123+456") → "579.00"
      - calculate("(1000-300)*2") → "1400.00"
      - calculate("2500-1000-500") → "1000.00"
      - calculate("(1500/2000)*100") → "75.00"
      - calculate("3733.35-1111.10+300+3000") → "5922.25"

    Args:
        expression: 标准四则运算表达式，如 "总收入-总支出+余额"

    Returns:
        计算结果，保留两位小数，或错误信息
    """
    # 安全校验
    is_valid, error_msg = validate_expression(expression)
    if not is_valid:
        logger.warning("计算器拦截非法表达式: %s → %s", expression[:80], error_msg)
        return f"计算错误：{error_msg}"

    # 清理空格
    safe_expr = CLEAN_RE.sub('', expression)

    # 沙箱执行
    try:
        # 使用受限的全局/局部命名空间防止注入
        result = eval(safe_expr, {"__builtins__": {}}, {})
    except ZeroDivisionError:
        logger.warning("计算器除零错误: %s", safe_expr)
        return "计算错误：除数不能为零"
    except SyntaxError as e:
        logger.warning("计算器语法错误: %s → %s", safe_expr, e)
        return f"计算错误：表达式语法不正确 — {e}"
    except Exception as e:
        logger.error("计算器异常: %s → %s", safe_expr, e)
        return f"计算错误：{e}"

    # 格式化输出：保留两位小数，去掉末尾无意义的零
    if isinstance(result, (int, float)):
        if result == int(result):
            formatted = f"{int(result)}.00"
        else:
            formatted = f"{result:.2f}"
        logger.debug("计算: %s = %s", safe_expr, formatted)
        return formatted
    else:
        return f"计算错误：结果类型异常 ({type(result).__name__})"
