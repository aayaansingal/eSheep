import random

from esheep.expressions import ExpressionContext, evaluate


def make_context(**overrides) -> ExpressionContext:
    values = dict(screen_w=1920, screen_h=1080, area_w=1920, area_h=1040,
                  image_w=40, image_h=40, random_spawn=50, rng=random.Random(1))
    values.update(overrides)
    return ExpressionContext(**values)


def test_plain_numbers():
    assert evaluate("200", make_context()) == 200
    assert evaluate("-2", make_context()) == -2


def test_screen_variables():
    assert evaluate("screenW+10", make_context()) == 1930
    assert evaluate("areaH-imageH", make_context()) == 1000
    assert evaluate("-imageH-20", make_context()) == -60


def test_division_is_real_and_result_truncates():
    # (1040/2 + (50*1040/2)/120 - 40) = 520 + 216.66 - 40 = 696.66 -> 696
    assert evaluate("areaH/2+(randS*areaH/2)/120-imageH", make_context()) == 696


def test_random_stays_in_range():
    context = make_context()
    values = {evaluate("random", context) for _ in range(500)}
    assert min(values) >= 0 and max(values) <= 99


def test_convert_int32_and_modulo():
    # Convert(960, System.Int32) % 30 = 0 -> 24 + 0/7 = 24
    assert evaluate("24+(Convert(screenW/2,System.Int32)%30)/7", make_context()) == 24
    # 683 % 30 = 23 -> 25 + 23/7 = 28.28 -> 28
    assert evaluate("25+(Convert(screenW/2,System.Int32)%30)/7", make_context(screen_w=1366)) == 28


def test_flipped_parent_mirrors_image_width():
    context = make_context(image_x=500, parent_flipped=True)
    # "-imageW" becomes "+imageW" so the child appears on the other side.
    assert evaluate("imageX-imageW*0.9", context) == 536
    assert evaluate("imageX+imageW", context) == 460


def test_invalid_and_malicious_input_evaluates_to_zero():
    context = make_context()
    assert evaluate("__import__('os').system('echo hi')", context) == 0
    assert evaluate("1/0", context) == 0
    assert evaluate("", context) == 0
    assert evaluate(None, context) == 0
