"""Evaluate the small arithmetic expressions used inside eSheep pet XML files.

The original Windows application substitutes a handful of variable names
(``screenW``, ``imageH``, ``random``...) with numbers and then hands the text to
.NET's ``DataTable.Compute``. We reproduce that behaviour with a whitelisted
``ast`` walker so that untrusted pet files can never execute arbitrary code.
"""

from __future__ import annotations

import ast
import math
import random as random_module
from dataclasses import dataclass, field


@dataclass
class ExpressionContext:
    """Values that pet expressions may refer to, all in logical pixels."""

    screen_w: int = 1920
    screen_h: int = 1080
    area_w: int = 1920
    area_h: int = 1040
    image_w: int = 40
    image_h: int = 40
    image_x: int = -1          # parent position, only meaningful for child pets
    image_y: int = -1
    random_spawn: int = 50     # "randS": fixed for the lifetime of one spawn
    scale: int = 1
    parent_flipped: bool = False
    rng: random_module.Random = field(default_factory=random_module.Random)


def substitute_variables(expression: str, context: ExpressionContext) -> str:
    """Replace variable names with numbers, in the same order as upstream."""
    text = expression

    # A child of a flipped parent must appear on the mirrored side of it.
    if context.parent_flipped:
        if "-imageW" in text:
            text = text.replace("-imageW", "+imageW")
        else:
            text = text.replace("imageW", "(-imageW)")

    replacements = [
        ("screenW", context.screen_w),
        ("screenH", context.screen_h),
        ("areaW", context.area_w),
        ("areaH", context.area_h),
        ("imageW", context.image_w),
        ("imageH", context.image_h),
        ("imageX", context.image_x),
        ("imageY", context.image_y),
        # Upstream draws a single random number per expression.
        ("random", context.rng.randint(0, 99)),
        ("randS", context.random_spawn),
        ("scale", context.scale),
    ]
    for name, value in replacements:
        text = text.replace(name, f"({value})")
    return text


def evaluate(expression: str | None, context: ExpressionContext) -> int:
    """Evaluate an XML expression to an integer (truncated like upstream).

    Invalid expressions evaluate to 0, which is what the original app does.
    """
    if expression is None or expression.strip() == "":
        return 0
    substituted = substitute_variables(expression, context)
    try:
        syntax_tree = ast.parse(substituted.strip(), mode="eval")
        value = _evaluate_node(syntax_tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError, OverflowError):
        return 0
    return int(value)


def _evaluate_node(node: ast.AST) -> float:
    """Recursively evaluate a whitelisted subset of Python expression syntax."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    if isinstance(node, ast.UnaryOp):
        operand = _evaluate_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand

    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            # .NET keeps the sign of the dividend, unlike Python's %.
            return math.fmod(left, right)

    if isinstance(node, ast.Call):
        return _evaluate_convert_call(node)

    raise ValueError(f"unsupported expression element: {ast.dump(node)}")


def _evaluate_convert_call(node: ast.Call) -> float:
    """Support DataTable's ``Convert(value, System.Int32)`` function."""
    function_name = node.func.id if isinstance(node.func, ast.Name) else ""
    if function_name.lower() != "convert" or len(node.args) != 2:
        raise ValueError("only Convert(value, type) calls are supported")

    value = _evaluate_node(node.args[0])
    target_type = ast.unparse(node.args[1]).lower()
    if "int" in target_type:
        # Convert.ToInt32 rounds half to even, just like Python's round().
        return round(value)
    return value
