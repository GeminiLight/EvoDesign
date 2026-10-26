"""Sequential keys compatible with Excalidraw's fractional indexing."""


def sequential_index(position: int) -> str:
    # The head encodes the integer-part length: a0, b00, ... e00000.
    # a00000 is invalid: it is a0 plus a fraction ending in zero.
    digits = str(position).zfill(5)
    if position < 0 or len(digits) > 26:
        raise ValueError("Canvas element position is out of range")
    return chr(ord("a") + len(digits) - 1) + digits
