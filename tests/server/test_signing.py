import pickle

import pytest
from src.private_billing.server.signing import Signer, TransferablePublicKey
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec

@pytest.fixture
def random_pk():
    return ec.generate_private_key(ec.SECP256K1()).public_key()

class TestTransferablePublicKey:
    
    def test_hash(self, random_pk):
        tpk = TransferablePublicKey(random_pk)
        assert isinstance(hash(tpk), int)

    def test_hash_is_constant(self, random_pk):
        tpk = TransferablePublicKey(random_pk)
        tpk = Signer().get_transferable_public_key()
        hash1 = hash(tpk)
        hash2 = hash(tpk)
        assert hash1 == hash2


class TestSigner:

    def test_signature_bytes(self):
        # Create object to sign
        obj = list(range(0, 10_000))
        obj_bytes = pickle.dumps(obj)

        # Sign object
        signer = Signer()
        signature = signer.sign(obj_bytes)

        # "Transfer" public verification key
        verification_key = signer.get_transferable_public_key()

        # Verify signature
        signer.verify(obj_bytes, signature, verification_key)

    def test_signature_obj(self):
        # Create object to sign
        obj = list(range(0, 10_000))

        # Sign object
        signer = Signer()
        signature = signer.sign(obj)

        # "Transfer" public verification key
        verification_key = signer.get_transferable_public_key()

        # Verify signature
        signer.verify(obj, signature, verification_key)

    def test_signature_does_not_verify_other_object(self):
        # Create object to sign
        obj = list(range(0, 10_000))

        # Sign object
        signer = Signer()
        signature = signer.sign(obj)

        # "Transfer" public verification key
        verification_key = signer.get_transferable_public_key()

        # Other object
        other_obj = "hello! these are some other, unsigned bytes"

        # Signature should not verify other_obj
        with pytest.raises(InvalidSignature):
            signer.verify(other_obj, signature, verification_key)

    def test_signature_does_not_verify_with_wrong_key(self):
        # Create object to sign
        obj = list(range(0, 10_000))

        # Sign object
        signer = Signer()
        signature = signer.sign(obj)

        # other signer
        other_verification_key = Signer().get_transferable_public_key()

        # Signature should fail with the other key
        with pytest.raises(InvalidSignature):
            signer.verify(obj, signature, other_verification_key)

    def test_serialization(self):
        # Create object to sign
        obj = list(range(0, 10_000))
        obj_bytes = pickle.dumps(obj)

        # Sign object
        signer = Signer()
        signature = signer.sign(obj_bytes)
        verification_key = signer.get_transferable_public_key()

        # Serialize objects
        msg = (obj, signature, verification_key)
        msg_bytes = pickle.dumps(msg)

        # ... transfer message as bytes ...

        # Reconstruct object
        rebuilt_obj, rebuilt_signature, rebuilt_key = pickle.loads(msg_bytes)

        # Verify signature
        signer.verify(rebuilt_obj, rebuilt_signature, rebuilt_key)
