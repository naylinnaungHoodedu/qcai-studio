"""Exact, platform-independent arithmetic for the ranking controller (spec 4.1; rule decimal-prec-34-half-even-quantize-1e-18-v1).

Every value is a decimal.Decimal computed inside localcontext(CTX) (34 digits, ROUND_HALF_EVEN, InvalidOperation,
DivisionByZero and Overflow trapped), so the ambient context of the calling thread never changes a result, and every
stored value is quantised to 1e-18 and written by to_str. A float is refused (D raises TypeError): the replay (AC-9-8)
must give the same bytes on every platform. The Beta quantile (eq. (7); rule
decimal-regularized-incomplete-beta-bisection-v1) is a fixed 60-step bisection over the regularized incomplete beta
function, computed by Lentz's continued fraction with a Stirling log-gamma; no scipy or numpy (neither is a dependency).
Randomness is uniform(): the first 8 bytes of a sha256 over the seed and the call's parts, never the random module.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext
from fractions import Fraction
from functools import lru_cache
import hashlib

CTX = Context(prec=34, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999, traps=[InvalidOperation, DivisionByZero, Overflow])
QUANTUM = Decimal("1e-18")
QUANTILE_QUANTUM = Decimal("1e-12")
BISECTION_STEPS = 60
CF_MAX_ITERATIONS = 600
CF_TOLERANCE = Decimal("1e-25")
FPMIN = Decimal("1e-300")
STIRLING_SHIFT = 30
PI = Decimal("3.14159265358979323846264338327950288419716939937510")
# B_2, B_4, ..., B_24 (exact).
BERNOULLI = (Fraction(1, 6), Fraction(-1, 30), Fraction(1, 42), Fraction(-1, 30), Fraction(5, 66), Fraction(-691, 2730), Fraction(7, 6),
             Fraction(-3617, 510), Fraction(43867, 798), Fraction(-174611, 330), Fraction(854513, 138), Fraction(-236364091, 2730))
ZERO, ONE = Decimal(0), Decimal(1)


def D(value) -> Decimal:
    """A Decimal from a str, an int or a Decimal; a float (or a bool) is refused."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"ranking arithmetic refuses {type(value).__name__} values: {value!r}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, str)):
        with localcontext(CTX):
            return Decimal(value)
    raise TypeError(f"ranking arithmetic refuses {type(value).__name__} values")


def q(value: Decimal) -> Decimal:
    with localcontext(CTX):
        return D(value).quantize(QUANTUM)


def to_str(value) -> str:
    """The canonical text of a value: quantised to 1e-18, trailing zeros removed, never an exponent, zero as "0"."""
    with localcontext(CTX):
        quantised = D(value).quantize(QUANTUM)
        if quantised == 0:
            return "0"
        return format(quantised.normalize(), "f")


def _fraction(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def log_gamma(x) -> Decimal:
    """ln Gamma(x) for x > 0: shift x up to at least 30, then the Stirling series with 12 Bernoulli terms."""
    with localcontext(CTX):
        x = D(x)
        if x <= 0:
            raise ArithmeticError("log_gamma needs x > 0")
        product = ONE
        while x < STIRLING_SHIFT:
            product *= x
            x += 1
        result = (x - Decimal("0.5")) * x.ln() - x + (2 * PI).ln() / 2
        power = x
        square = x * x
        for k, bernoulli in enumerate(BERNOULLI, start=1):
            result += _fraction(bernoulli) / (Decimal(2 * k) * Decimal(2 * k - 1) * power)
            power *= square
        return result - product.ln()


def ln_beta(a, b) -> Decimal:
    with localcontext(CTX):
        a, b = D(a), D(b)
        return log_gamma(a) + log_gamma(b) - log_gamma(a + b)


def _continued_fraction(x: Decimal, a: Decimal, b: Decimal) -> Decimal:
    qab, qap, qam = a + b, a + 1, a - 1
    c = ONE
    d = ONE - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = ONE / d
    h = d
    for m in range(1, CF_MAX_ITERATIONS + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = ONE + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = ONE + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = ONE / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = ONE + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = ONE + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = ONE / d
        delta = d * c
        h *= delta
        if abs(delta - ONE) < CF_TOLERANCE:
            return h
    raise ArithmeticError("the incomplete beta continued fraction did not converge")


def reg_inc_beta(x, a, b, *, lnb: Decimal | None = None) -> Decimal:
    """I_x(a, b), the regularized incomplete beta function; I_0 = 0 and I_1 = 1 exactly."""
    with localcontext(CTX):
        x, a, b = D(x), D(a), D(b)
        if a <= 0 or b <= 0:
            raise ArithmeticError("reg_inc_beta needs a > 0 and b > 0")
        if x <= 0:
            return ZERO
        if x >= 1:
            return ONE
        if lnb is None:
            lnb = ln_beta(a, b)
        prefactor = (a * x.ln() + b * (ONE - x).ln() - lnb).exp()
        if x < (a + 1) / (a + b + 2):
            return prefactor * _continued_fraction(x, a, b) / a
        return ONE - prefactor * _continued_fraction(ONE - x, b, a) / b


def beta_quantile(p, a, b) -> Decimal:
    """F^-1_Beta(p; a, b): exactly 60 bisection steps on [0, 1] (no early exit), the lower end quantised to 1e-12."""
    return _beta_quantile(to_str(p), to_str(a), to_str(b))


@lru_cache(maxsize=65536)
def _beta_quantile(p: str, a: str, b: str) -> Decimal:
    with localcontext(CTX):
        p, a, b = D(p), D(a), D(b)
        if not ZERO < p < ONE:
            raise ArithmeticError("beta_quantile needs 0 < p < 1")
        lnb = ln_beta(a, b)
        lo, hi = ZERO, ONE
        for _ in range(BISECTION_STEPS):
            mid = (lo + hi) / 2
            if reg_inc_beta(mid, a, b, lnb=lnb) < p:
                lo = mid
            else:
                hi = mid
        return lo.quantize(QUANTILE_QUANTUM)


def ln_ratio(p0, p1) -> tuple[Decimal, Decimal]:
    """(A, B) of eq. (11): A = ln(p1/p0) for an error, B = ln((1-p1)/(1-p0)) for a clean response."""
    return _ln_ratio(to_str(p0), to_str(p1))


@lru_cache(maxsize=64)
def _ln_ratio(p0: str, p1: str) -> tuple[Decimal, Decimal]:
    with localcontext(CTX):
        p0, p1 = D(p0), D(p1)
        return q((p1 / p0).ln()), q(((ONE - p1) / (ONE - p0)).ln())


def uniform(seed: str, *parts: str) -> Decimal:
    """A deterministic draw in [0, 1): the first 8 bytes of sha256("ranking-v1|seed|parts...") over 2^64 (sha256-u64-v1)."""
    digest = hashlib.sha256("|".join(("ranking-v1", seed, *parts)).encode("utf-8")).digest()
    with localcontext(CTX):
        return q(Decimal(int.from_bytes(digest[:8], "big")) / Decimal(2**64))
