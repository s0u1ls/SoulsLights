"""Zero-dependency ISO/IEC 18004 QR Code matrix & PIL RGBA renderer (Versions 1-6, Level L)."""

from PIL import Image, ImageDraw

# GF(256) tables with primitive polynomial x^8 + x^4 + x^3 + x^2 + 1 (0x11d)
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_EXP[_i + 255] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator(degree: int) -> list:
    poly = [1]
    for i in range(degree):
        # Multiply poly by (x - alpha^i) in GF(256)
        nxt = [0] * (len(poly) + 1)
        g = _GF_EXP[i]
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _gf_mul(c, g)
        poly = nxt
    return poly


def _rs_remainder(data: list, ecc_len: int) -> list:
    gen = _rs_generator(ecc_len)
    res = list(data) + [0] * ecc_len
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


# Single-block Level L parameters: (version, size, total_data_bytes, ecc_bytes, align_centers)
_VER_SPEC = [
    (1, 21, 19, 7, []),
    (2, 25, 34, 10, [6, 18]),
    (3, 29, 55, 15, [6, 22]),
    (4, 33, 80, 20, [6, 26]),
    (5, 37, 108, 26, [6, 30]),
]

_MASK_FNS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: ((r // 2) + (c // 3)) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


def _format_bits(mask_idx: int) -> int:
    # Level L = 0b01
    data = (0b01 << 3) | (mask_idx & 7)
    rem = data << 10
    while rem.bit_length() >= 11:
        rem ^= 0x537 << (rem.bit_length() - 11)
    return ((data << 10) | rem) ^ 0x5412


def _penalty_score(mat: list) -> int:
    n = len(mat)
    score = 0
    # Rule 1: adjacent runs >= 5
    for r in range(n):
        run = 1
        for c in range(1, n):
            if mat[r][c] == mat[r][c - 1]:
                run += 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            else:
                run = 1
    for c in range(n):
        run = 1
        for r in range(1, n):
            if mat[r][c] == mat[r - 1][c]:
                run += 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            else:
                run = 1
    # Rule 2: 2x2 blocks
    for r in range(n - 1):
        for c in range(n - 1):
            v = mat[r][c]
            if v == mat[r][c + 1] == mat[r + 1][c] == mat[r + 1][c + 1]:
                score += 3
    # Rule 4: dark ratio balance
    dark = sum(sum(row) for row in mat)
    pct = (dark * 100) // (n * n)
    score += (abs(pct - 50) // 5) * 10
    return score


def make_qr_matrix(text: str) -> list:
    """Encodes text (UTF-8 Byte mode) into an ISO/IEC 18004 Level-L QR boolean matrix."""
    raw = (text or "").encode("utf-8")
    spec = None
    for row in _VER_SPEC:
        # 4-bit mode + 8-bit len + 8-bit * len <= data_bytes * 8 - 4 (safe margin)
        if len(raw) + 2 <= row[2]:
            spec = row
            break
    if spec is None:
        raw = raw[: _VER_SPEC[-1][2] - 2]
        spec = _VER_SPEC[-1]

    ver, n, data_cap, ecc_len, align = spec

    bits = []
    def _push(val: int, width: int):
        for b in range(width - 1, -1, -1):
            bits.append((val >> b) & 1)

    _push(0b0100, 4)        # Byte mode indicator
    _push(len(raw), 8)      # Character count (8 bits for V1-9)
    for byte in raw:
        _push(byte, 8)
    _push(0, min(4, data_cap * 8 - len(bits)))  # Terminator
    while len(bits) % 8 != 0:
        bits.append(0)

    data_bytes = []
    for i in range(0, len(bits), 8):
        bval = 0
        for j in range(8):
            bval = (bval << 1) | bits[i + j]
        data_bytes.append(bval)

    pad_cycle = (0xEC, 0x11)
    pi = 0
    while len(data_bytes) < data_cap:
        data_bytes.append(pad_cycle[pi & 1])
        pi += 1

    ecc_bytes = _rs_remainder(data_bytes, ecc_len)
    all_bytes = data_bytes + ecc_bytes
    stream = []
    for bv in all_bytes:
        for b in range(7, -1, -1):
            stream.append((bv >> b) & 1)

    base = [[None] * n for _ in range(n)]
    func = [[False] * n for _ in range(n)]

    def _set(r: int, c: int, val: int):
        if 0 <= r < n and 0 <= c < n:
            base[r][c] = 1 if val else 0
            func[r][c] = True

    def _draw_finder(r0: int, c0: int):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = r0 + dr, c0 + dc
                if not (0 <= r < n and 0 <= c < n):
                    continue
                if dr in (-1, 7) or dc in (-1, 7):
                    _set(r, c, 0)
                elif dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4):
                    _set(r, c, 1)
                else:
                    _set(r, c, 0)

    _draw_finder(0, 0)
    _draw_finder(0, n - 7)
    _draw_finder(n - 7, 0)

    for i in range(8, n - 8):
        v = 1 - (i & 1)
        _set(6, i, v)
        _set(i, 6, v)

    for ar in align:
        for ac in align:
            if func[ar][ac]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = 1 if (abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)) else 0
                    _set(ar + dr, ac + dc, val)

    # Reserve format info cells & dark module
    for i in range(9):
        if i != 6:
            func[8][i] = True
            func[i][8] = True
    for i in range(n - 8, n):
        func[8][i] = True
    for i in range(n - 7, n):
        func[i][8] = True
    _set(n - 8, 8, 1)

    # Zig-zag bit placement
    bit_i = 0
    col = n - 1
    up = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(n - 1, -1, -1) if up else range(n)
        for row in rows:
            for c_off in (0, -1):
                c = col + c_off
                if not func[row][c]:
                    b_val = stream[bit_i] if bit_i < len(stream) else 0
                    base[row][c] = b_val
                    bit_i += 1
        col -= 2
        up = not up

    # Evaluate all 8 masks and pick lowest penalty
    best_mat = None
    best_score = 10**9
    for m_idx, m_fn in enumerate(_MASK_FNS):
        cand = [row[:] for row in base]
        for r in range(n):
            for c in range(n):
                if not func[r][c] and m_fn(r, c):
                    cand[r][c] ^= 1
        fmt = _format_bits(m_idx)
        # Format bits 0..14 placed per ISO/IEC 18004 Figure 25 (bit 14 MSB at top-left col 8 row 0 / bit 0 at row 8 col 0)
        tl_coords = [
            (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
            (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
        ]
        for k in range(15):
            bit_v = (fmt >> (14 - k)) & 1
            # Primary copy top-left
            r1, c1 = tl_coords[k]
            # Top-left mapping in ISO 18004: bit 14 at (8,0) .. bit 8 at (8,7), bit 7 at (8,8), bit 6 at (7,8) .. bit 0 at (0,8)
            cand[r1][c1] = bit_v
            # Secondary copy split between bottom-left (bits 14..8 from bottom up: (n-1,8)..(n-7,8)) and top-right (bits 7..0: (8,n-8)..(8,n-1))
            if k < 7:
                cand[n - 1 - k][8] = bit_v
            else:
                cand[8][n - 15 + k] = bit_v
        sc = _penalty_score(cand)
        if sc < best_score:
            best_score = sc
            best_mat = cand

    return best_mat


def render_qr_rgba(text: str, target_size: int = 112, fg=(15, 17, 26, 255), bg=(250, 250, 255, 255)) -> Image.Image:
    """Renders a crisp scannable QR code rounded-card Image.Image with full 4-module quiet zone."""
    mat = make_qr_matrix(text)
    n = len(mat)
    quiet = 4
    mod_total = n + quiet * 2
    scale = max(2, (target_size + mod_total - 1) // mod_total)
    raw_sz = mod_total * scale
    img = Image.new("RGBA", (raw_sz, raw_sz), bg)
    d = ImageDraw.Draw(img)
    for r in range(n):
        for c in range(n):
            if mat[r][c]:
                x0 = (c + quiet) * scale
                y0 = (r + quiet) * scale
                d.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=fg)
    if raw_sz != target_size:
        img = img.resize((target_size, target_size), Image.Resampling.NEAREST)
    return img
