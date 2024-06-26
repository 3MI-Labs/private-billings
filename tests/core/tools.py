from src.private_billing.core import (
    Bill,
    CycleContext,
    HiddenBill,
    HidingContext,
    SharedMaskGenerator,
    Int64Convertor,
    PublicHidingContext,
    vector,
)
from openfhe import Ciphertext


class TestConvertor(Int64Convertor):
    def convert_from_int64(self, val: int):
        return val


def get_test_convertor():
    return TestConvertor()


def get_test_cycle_context(id, length: int):
    return CycleContext(
        id,
        length,
        vector([0.21] * length),
        vector([0.05] * length),
        vector([0.11] * length),
    )


def get_test_mask_generator():
    conv = get_test_convertor()
    return SharedMaskGenerator(conv)


class MockedHidingContext(HidingContext):
    """
    Mock for Hiding Context

    encrypt = add one
    decrypt = subtract one
    mask = value + iv
    """

    def __init__(self, cyc: CycleContext, mask_generator: SharedMaskGenerator) -> None:
        self.cyc = cyc
        self.mask_generator = mask_generator
        self.cc = "cc"

    @property
    def public_key(self):
        return "pk"

    @property
    def _secret_key(self):
        return "sk"

    def get_masking_iv(self, round: int, obj_name: str) -> int:
        return 5

    def mask(self, values: list[float], iv: int) -> list[float]:
        return [v + iv for v in values]

    def encrypt(self, values: list[float]):
        return [v + 1 for v in values]

    def decrypt(self, values: list[float]):
        return [v - 1 for v in values]

    def get_public_hiding_context(self):
        return MockedPublicHidingContext("cyc", "cc", "pk")


def get_mock_hiding_context():
    return MockedHidingContext("cyc", "mg")


class MockedPublicHidingContext(PublicHidingContext):

    def invert_flags(self, vals):
        return vector([1 - v for v in vals])

    def encrypt(self, scalars: list[float], pk):
        return vector(scalars)

    def scale(self, ctxt, scalars: list[float]):
        return vector([c * s for c, s in zip(ctxt, scalars)])

    def multiply(self, ctxt_1, ctxt_2):
        return vector([c1 * c2 for c1, c2 in zip(ctxt_1, ctxt_2)])

    def __eq__(self, o):
        return self.cc == o.cc and self.public_key == o.public_key

    def activate_keys(self) -> None:
        pass

def get_mock_public_hiding_context():
    return MockedPublicHidingContext("cyc", "cc", "pk")


ERROR = pow(10, -10)


def are_equal_ciphertexts(c1: Ciphertext, c2: Ciphertext, hc: HidingContext) -> bool:
    p1 = hc.decrypt(c1)
    p2 = hc.decrypt(c2)

    if len(p1) != len(p2):
        return False

    are_equal = True
    for e1, e2 in zip(p1, p2):
        are_equal &= abs(e1 - e2) < ERROR
    return are_equal

class HiddenBillMock(HiddenBill):
    def reveal(self, hc: HidingContext):
        return Bill(self.cycle_id, self.hidden_bill, self.hidden_reward)