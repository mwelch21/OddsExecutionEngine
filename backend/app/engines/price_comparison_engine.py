def is_price_fillable(price: int, target_price: int) -> bool:
    return price >= target_price


def compare_prices(left_price: int, right_price: int) -> int:
    if left_price > right_price:
        return 1

    if left_price < right_price:
        return -1

    return 0
